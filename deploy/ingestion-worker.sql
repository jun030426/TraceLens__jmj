-- Additive ingestion worker extension. Existing app jobs and shared RAG are unchanged.
CREATE TABLE IF NOT EXISTS public.shorts_scripts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 job_id uuid NOT NULL REFERENCES public.ingestion_jobs(id),
 course_id varchar(36) NOT NULL REFERENCES public.courses(id),
 concept_id text NOT NULL CHECK (length(concept_id) BETWEEN 1 AND 200),
 shorts_key text NOT NULL CHECK (length(shorts_key) BETWEEN 1 AND 200),
 title text NOT NULL CHECK (length(btrim(title))>0),
 template_variables jsonb NOT NULL CHECK (jsonb_typeof(template_variables)='object'
   AND template_variables ? 'lecture_script' AND jsonb_typeof(template_variables->'lecture_script')='string'
   AND length(btrim(template_variables->>'lecture_script'))>0),
 evidence jsonb NOT NULL CHECK (jsonb_typeof(evidence)='array' AND jsonb_array_length(evidence)>0),
 generator_version text NOT NULL,
 lease_token uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(job_id,shorts_key)
);
ALTER TABLE public.shorts_scripts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.shorts_scripts FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.shorts_scripts TO service_role;
CREATE INDEX IF NOT EXISTS shorts_scripts_course_idx ON public.shorts_scripts(course_id);
CREATE OR REPLACE FUNCTION public.ingestion_guard_shorts()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $$
DECLARE source_course varchar(36);
BEGIN
 SELECT s.course_id INTO source_course FROM public.ingestion_sources s
 JOIN public.ingestion_jobs j ON j.source_id=s.id WHERE j.id=new.job_id;
 IF source_course IS DISTINCT FROM new.course_id THEN RAISE EXCEPTION 'SHORTS_SCOPE_MISMATCH'; END IF;
 RETURN new;
END $$;
DROP TRIGGER IF EXISTS shorts_scripts_write_guard ON public.shorts_scripts;
CREATE TRIGGER shorts_scripts_write_guard BEFORE INSERT OR UPDATE ON public.shorts_scripts
 FOR EACH ROW EXECUTE FUNCTION public.ingestion_guard_result_write();
DROP TRIGGER IF EXISTS shorts_scripts_scope_guard ON public.shorts_scripts;
CREATE TRIGGER shorts_scripts_scope_guard BEFORE INSERT OR UPDATE ON public.shorts_scripts
 FOR EACH ROW EXECUTE FUNCTION public.ingestion_guard_shorts();
REVOKE ALL ON FUNCTION public.ingestion_guard_shorts() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ingestion_guard_shorts() TO service_role;

CREATE TABLE IF NOT EXISTS public.ingestion_api_pacing (
 id boolean PRIMARY KEY DEFAULT true CHECK(id),
 next_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.ingestion_api_pacing ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ingestion_api_pacing FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.ingestion_api_pacing TO service_role;
CREATE OR REPLACE FUNCTION public.ingestion_reserve_api_slot()
RETURNS double precision LANGUAGE plpgsql SET search_path='' AS $$
DECLARE slot timestamptz;
BEGIN
 INSERT INTO public.ingestion_api_pacing(id,next_at) VALUES(true,clock_timestamp())
 ON CONFLICT(id) DO NOTHING;
 SELECT greatest(next_at,clock_timestamp()) INTO slot FROM public.ingestion_api_pacing WHERE id FOR UPDATE;
 UPDATE public.ingestion_api_pacing SET next_at=slot+interval '4.5 seconds' WHERE id;
 RETURN greatest(0,extract(epoch FROM slot-clock_timestamp()));
END $$;
REVOKE ALL ON FUNCTION public.ingestion_reserve_api_slot() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ingestion_reserve_api_slot() TO service_role;

CREATE OR REPLACE FUNCTION public.ingestion_publish(p_job_id uuid, p_lease_token uuid, p_expected_vectors integer, p_expected_concept_quizzes integer, p_expected_lab_quizzes integer)
 RETURNS ingestion_jobs
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare j public.ingestion_jobs; s public.ingestion_sources; nv integer; nc integer; nl integer; ns integer; expected jsonb;
begin
  -- Same source lock order as enqueue; only the newest requested version can become active.
  select s0.* into s from public.ingestion_sources s0 join public.ingestion_jobs j0 on j0.source_id=s0.id
    where j0.id=p_job_id for update of s0;
  if not found then raise exception 'JOB_NOT_FOUND'; end if;
  select * into j from public.ingestion_jobs where id=p_job_id for update;
  if j.status<>'PROCESSING' or j.lease_token is distinct from p_lease_token or j.lease_until<=now()
    then raise exception 'STALE_LEASE'; end if;
  if j.last_completed_stage<>5 then raise exception 'CHECKPOINTS_INCOMPLETE'; end if;
  select count(*) into nv from public.course_vectors where job_id=p_job_id;
  select count(*) into nc from public.concept_quizzes where job_id=p_job_id;
  select count(*) into nl from public.lab_quizzes where job_id=p_job_id;
  if p_expected_vectors is null or p_expected_vectors<1 or nv<>p_expected_vectors
    or p_expected_concept_quizzes is null or p_expected_concept_quizzes<0 or nc<>p_expected_concept_quizzes
    or p_expected_lab_quizzes is null or p_expected_lab_quizzes<0 or nl<>p_expected_lab_quizzes
    then raise exception 'RESULT_COUNTS_MISMATCH'; end if;
  if nc+nl=0 and not exists(select 1 from public.ingestion_checkpoints
    where job_id=p_job_id and stage=5 and output->>'skipped'='true' and length(output->>'reason')>0)
    then raise exception 'QUIZ_RESULTS_REQUIRED'; end if;
  select count(*) into ns from public.shorts_scripts where job_id=p_job_id;
  if j.pipeline_version='ingestion-worker-v1' then
    if s.visibility<>'public' or s.internal_use<>'none' then raise exception 'SOURCE_NOT_PUBLIC'; end if;
    select output->'expected_counts' into expected from public.ingestion_checkpoints where job_id=p_job_id and stage=5;
    if nc<1 or ns<1 or expected is null or
       (expected->>'course_vectors')::integer is distinct from nv or
       (expected->>'concept_quizzes')::integer is distinct from nc or
       (expected->>'shorts_scripts')::integer is distinct from ns or
       (expected->>'lab_quizzes')::integer is distinct from nl then
      raise exception 'SHORTS_RESULTS_REQUIRED';
    end if;
  end if;
  update public.ingestion_jobs set
    status=case when s.latest_job_id is distinct from p_job_id then 'SUPERSEDED'
      when jsonb_array_length(review_items)>0 then 'PARTIAL_SUCCESS' else 'COMPLETED' end,
    current_stage='DONE',last_completed_stage=6,progress_percentage=100,
    result=jsonb_build_object('vectors',nv,'concept_quizzes',nc,'lab_quizzes',nl,'shorts_scripts',ns,'published',s.latest_job_id=p_job_id),
    lease_token=null,lease_until=null,worker_id=null,finished_at=now(),updated_at=now()
    where id=p_job_id returning * into j;
  if s.latest_job_id=p_job_id then
    update public.ingestion_sources set active_job_id=p_job_id,updated_at=now() where id=s.id;
  end if;
  return j;
end $function$
;
REVOKE ALL ON FUNCTION public.ingestion_publish(uuid,uuid,integer,integer,integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ingestion_publish(uuid,uuid,integer,integer,integer) TO service_role;
CREATE OR REPLACE FUNCTION public.ingestion_claim(p_worker_id text, p_lease_seconds integer, p_pipeline_version text)
 RETURNS SETOF ingestion_jobs
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
  if p_pipeline_version is null or length(p_pipeline_version) not between 1 and 100 then raise exception 'INVALID_PIPELINE'; end if;
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 100
    or p_lease_seconds is null or p_lease_seconds not between 30 and 900 then
    raise exception 'INVALID_WORKER_OR_LEASE';
  end if;
  -- Expired claims consume the same bounded attempt budget as explicit failures.
  with exhausted as (
    select id from public.ingestion_jobs where pipeline_version=p_pipeline_version and attempt_count>=max_attempts and
      (status='PENDING' or (status='PROCESSING' and lease_until<=now()))
      order by created_at for update skip locked limit 100
  ) update public.ingestion_jobs j set status='FAILED',error_code='ATTEMPTS_EXHAUSTED',
    lease_token=null,lease_until=null,worker_id=null,finished_at=now(),updated_at=now()
    from exhausted e where j.id=e.id;
  return query
    with candidate as (
      select id from public.ingestion_jobs where pipeline_version=p_pipeline_version and attempt_count<max_attempts and
        ((status='PENDING' and available_at<=now()) or (status='PROCESSING' and lease_until<=now()))
        order by available_at,created_at,id for update skip locked limit 1
    ) update public.ingestion_jobs j set status='PROCESSING',worker_id=p_worker_id,
      lease_token=gen_random_uuid(),lease_until=now()+make_interval(secs=>p_lease_seconds),
      heartbeat_at=now(),attempt_count=attempt_count+1,started_at=coalesce(started_at,now()),
      error_code=null,error_message=null,finished_at=null,updated_at=now()
      from candidate c where j.id=c.id returning j.*;
end $function$
;
REVOKE ALL ON FUNCTION public.ingestion_claim(text,integer,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ingestion_claim(text,integer,text) TO service_role;

NOTIFY pgrst, 'reload schema';

