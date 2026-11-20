-- Snapshot of the existing ingestion schema (2026-11-10). For isolated tests/fresh installs.
-- Requires existing public.courses/public.users and pgcrypto/pgvector.
CREATE TABLE public.concept_quizzes (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  job_id uuid NOT NULL,
  quiz_key text NOT NULL,
  concept_label text NOT NULL,
  question_type text NOT NULL,
  difficulty text NOT NULL,
  question text NOT NULL,
  options jsonb DEFAULT '[]'::jsonb NOT NULL,
  answer jsonb NOT NULL,
  explanation text NOT NULL,
  hints jsonb NOT NULL,
  evidence jsonb DEFAULT '[]'::jsonb NOT NULL,
  generator_version text NOT NULL,
  lease_token uuid NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.course_vectors (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  job_id uuid NOT NULL,
  chunk_key text NOT NULL,
  content text NOT NULL,
  locator jsonb DEFAULT '{}'::jsonb NOT NULL,
  concept_label text,
  embedding_model text NOT NULL,
  embedding vector NOT NULL,
  embedding_dimensions integer GENERATED ALWAYS AS (vector_dims(embedding)) STORED,
  lease_token uuid NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.ingestion_checkpoints (
  job_id uuid NOT NULL,
  stage smallint NOT NULL,
  output jsonb NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.ingestion_jobs (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  source_id uuid NOT NULL,
  file_name text NOT NULL,
  storage_bucket text DEFAULT 'lerny-materials'::text NOT NULL,
  file_path text NOT NULL,
  file_hash text NOT NULL,
  pipeline_version text NOT NULL,
  config jsonb DEFAULT '{}'::jsonb NOT NULL,
  config_hash text GENERATED ALWAYS AS (encode(digest((config)::text, 'sha256'::text), 'hex'::text)) STORED,
  status text DEFAULT 'PENDING'::text NOT NULL,
  current_stage text DEFAULT 'DOWNLOADING'::text NOT NULL,
  last_completed_stage smallint DEFAULT 0 NOT NULL,
  progress_percentage smallint DEFAULT 0 NOT NULL,
  attempt_count integer DEFAULT 0 NOT NULL,
  max_attempts integer DEFAULT 4 NOT NULL,
  available_at timestamp with time zone DEFAULT now() NOT NULL,
  worker_id text,
  lease_token uuid,
  lease_until timestamp with time zone,
  heartbeat_at timestamp with time zone,
  error_code text,
  error_message text,
  review_items jsonb DEFAULT '[]'::jsonb NOT NULL,
  result jsonb,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  updated_at timestamp with time zone DEFAULT now() NOT NULL,
  started_at timestamp with time zone,
  finished_at timestamp with time zone
);
CREATE TABLE public.ingestion_sources (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  course_id character varying(36) NOT NULL,
  source_key text NOT NULL,
  title text NOT NULL,
  week_number smallint NOT NULL,
  visibility text DEFAULT 'private'::text NOT NULL,
  internal_use text DEFAULT 'none'::text NOT NULL,
  created_by character varying(36) NOT NULL,
  latest_job_id uuid,
  active_job_id uuid,
  created_at timestamp with time zone DEFAULT now() NOT NULL,
  updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.lab_quizzes (
  id uuid DEFAULT gen_random_uuid() NOT NULL,
  job_id uuid NOT NULL,
  quiz_key text NOT NULL,
  language text NOT NULL,
  target_score smallint NOT NULL,
  question text NOT NULL,
  code_template text NOT NULL,
  blanks jsonb NOT NULL,
  solution jsonb NOT NULL,
  explanation text NOT NULL,
  hints jsonb DEFAULT '[]'::jsonb NOT NULL,
  evidence jsonb DEFAULT '[]'::jsonb NOT NULL,
  generator_version text NOT NULL,
  lease_token uuid NOT NULL,
  created_at timestamp with time zone DEFAULT now() NOT NULL
);
ALTER TABLE public.concept_quizzes ADD CONSTRAINT concept_quizzes_pkey PRIMARY KEY (id);
ALTER TABLE public.course_vectors ADD CONSTRAINT course_vectors_pkey PRIMARY KEY (id);
ALTER TABLE public.ingestion_checkpoints ADD CONSTRAINT ingestion_checkpoints_pkey PRIMARY KEY (job_id, stage);
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_pkey PRIMARY KEY (id);
ALTER TABLE public.ingestion_sources ADD CONSTRAINT ingestion_sources_pkey PRIMARY KEY (id);
ALTER TABLE public.lab_quizzes ADD CONSTRAINT lab_quizzes_pkey PRIMARY KEY (id);
ALTER TABLE public.concept_quizzes ADD CONSTRAINT concept_quizzes_job_id_quiz_key_key UNIQUE (job_id, quiz_key);
ALTER TABLE public.course_vectors ADD CONSTRAINT course_vectors_job_id_chunk_key_key UNIQUE (job_id, chunk_key);
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_source_id_file_hash_pipeline_version_config__key UNIQUE (source_id, file_hash, pipeline_version, config_hash);
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_source_id_id_key UNIQUE (source_id, id);
ALTER TABLE public.ingestion_sources ADD CONSTRAINT ingestion_sources_course_id_source_key_key UNIQUE (course_id, source_key);
ALTER TABLE public.lab_quizzes ADD CONSTRAINT lab_quizzes_job_id_quiz_key_key UNIQUE (job_id, quiz_key);
ALTER TABLE public.concept_quizzes ADD CONSTRAINT concept_quizzes_answer_check CHECK ((jsonb_typeof(answer) = 'object'::text));
ALTER TABLE public.concept_quizzes ADD CONSTRAINT concept_quizzes_difficulty_check CHECK ((difficulty = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])));
ALTER TABLE public.concept_quizzes ADD CONSTRAINT concept_quizzes_evidence_check CHECK ((jsonb_typeof(evidence) = 'array'::text));
ALTER TABLE public.concept_quizzes ADD CONSTRAINT concept_quizzes_hints_check CHECK (((jsonb_typeof(hints) = 'array'::text) AND (jsonb_array_length(hints) = 3)));
ALTER TABLE public.concept_quizzes ADD CONSTRAINT concept_quizzes_options_check CHECK ((jsonb_typeof(options) = 'array'::text));
ALTER TABLE public.concept_quizzes ADD CONSTRAINT concept_quizzes_question_check CHECK ((length(btrim(question)) > 0));
ALTER TABLE public.concept_quizzes ADD CONSTRAINT concept_quizzes_question_type_check CHECK ((question_type = ANY (ARRAY['principle'::text, 'trace'::text, 'scenario'::text, 'comparison'::text])));
ALTER TABLE public.concept_quizzes ADD CONSTRAINT concept_quizzes_quiz_key_check CHECK (((length(quiz_key) >= 1) AND (length(quiz_key) <= 200)));
ALTER TABLE public.course_vectors ADD CONSTRAINT course_vectors_chunk_key_check CHECK (((length(chunk_key) >= 1) AND (length(chunk_key) <= 200)));
ALTER TABLE public.course_vectors ADD CONSTRAINT course_vectors_content_check CHECK ((length(btrim(content)) > 0));
ALTER TABLE public.course_vectors ADD CONSTRAINT course_vectors_embedding_check CHECK ((vector_norm(embedding) > (0)::double precision));
ALTER TABLE public.course_vectors ADD CONSTRAINT course_vectors_embedding_model_check CHECK (((length(embedding_model) >= 1) AND (length(embedding_model) <= 200)));
ALTER TABLE public.course_vectors ADD CONSTRAINT course_vectors_locator_check CHECK ((jsonb_typeof(locator) = 'object'::text));
ALTER TABLE public.ingestion_checkpoints ADD CONSTRAINT ingestion_checkpoints_output_check CHECK ((jsonb_typeof(output) = 'object'::text));
ALTER TABLE public.ingestion_checkpoints ADD CONSTRAINT ingestion_checkpoints_stage_check CHECK (((stage >= 1) AND (stage <= 5)));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_attempt_count_check CHECK ((attempt_count >= 0));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_check CHECK ((((status = 'PROCESSING'::text) AND (lease_token IS NOT NULL) AND (lease_until IS NOT NULL) AND (worker_id IS NOT NULL)) OR ((status <> 'PROCESSING'::text) AND (lease_token IS NULL) AND (lease_until IS NULL))));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_config_check CHECK ((jsonb_typeof(config) = 'object'::text));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_current_stage_check CHECK ((current_stage = ANY (ARRAY['DOWNLOADING'::text, 'EXTRACTING'::text, 'VALIDATING'::text, 'INDEXING'::text, 'QUIZ_GENERATING'::text, 'PUBLISHING'::text, 'DONE'::text])));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_file_hash_check CHECK ((file_hash ~ '^[0-9a-f]{64}$'::text));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_file_name_check CHECK (((length(file_name) >= 1) AND (length(file_name) <= 255)));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_file_path_check CHECK (((file_path ~~ 'ingestion/raw/%'::text) AND (POSITION(('..'::text) IN (file_path)) = 0)));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_last_completed_stage_check CHECK (((last_completed_stage >= 0) AND (last_completed_stage <= 6)));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_max_attempts_check CHECK (((max_attempts >= 1) AND (max_attempts <= 10)));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_pipeline_version_check CHECK (((length(pipeline_version) >= 1) AND (length(pipeline_version) <= 100)));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_progress_percentage_check CHECK (((progress_percentage >= 0) AND (progress_percentage <= 100)));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_review_items_check CHECK ((jsonb_typeof(review_items) = 'array'::text));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_status_check CHECK ((status = ANY (ARRAY['PENDING'::text, 'PROCESSING'::text, 'COMPLETED'::text, 'PARTIAL_SUCCESS'::text, 'FAILED'::text, 'SUPERSEDED'::text])));
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_storage_bucket_check CHECK ((storage_bucket = 'lerny-materials'::text));
ALTER TABLE public.ingestion_sources ADD CONSTRAINT ingestion_sources_internal_use_check CHECK ((internal_use = ANY (ARRAY['none'::text, 'validation_grading'::text])));
ALTER TABLE public.ingestion_sources ADD CONSTRAINT ingestion_sources_source_key_check CHECK (((length(source_key) >= 1) AND (length(source_key) <= 200)));
ALTER TABLE public.ingestion_sources ADD CONSTRAINT ingestion_sources_title_check CHECK (((length(title) >= 1) AND (length(title) <= 500)));
ALTER TABLE public.ingestion_sources ADD CONSTRAINT ingestion_sources_visibility_check CHECK ((visibility = ANY (ARRAY['private'::text, 'public'::text])));
ALTER TABLE public.ingestion_sources ADD CONSTRAINT ingestion_sources_week_number_check CHECK (((week_number >= 1) AND (week_number <= 52)));
ALTER TABLE public.lab_quizzes ADD CONSTRAINT lab_quizzes_blanks_check CHECK (((jsonb_typeof(blanks) = 'array'::text) AND (jsonb_array_length(blanks) > 0)));
ALTER TABLE public.lab_quizzes ADD CONSTRAINT lab_quizzes_evidence_check CHECK ((jsonb_typeof(evidence) = 'array'::text));
ALTER TABLE public.lab_quizzes ADD CONSTRAINT lab_quizzes_hints_check CHECK ((jsonb_typeof(hints) = 'array'::text));
ALTER TABLE public.lab_quizzes ADD CONSTRAINT lab_quizzes_quiz_key_check CHECK (((length(quiz_key) >= 1) AND (length(quiz_key) <= 200)));
ALTER TABLE public.lab_quizzes ADD CONSTRAINT lab_quizzes_solution_check CHECK ((jsonb_typeof(solution) = 'object'::text));
ALTER TABLE public.lab_quizzes ADD CONSTRAINT lab_quizzes_target_score_check CHECK ((target_score = ANY (ARRAY[80, 90, 100])));
ALTER TABLE public.concept_quizzes ADD CONSTRAINT concept_quizzes_job_id_fkey FOREIGN KEY (job_id) REFERENCES ingestion_jobs(id);
ALTER TABLE public.course_vectors ADD CONSTRAINT course_vectors_job_id_fkey FOREIGN KEY (job_id) REFERENCES ingestion_jobs(id);
ALTER TABLE public.ingestion_checkpoints ADD CONSTRAINT ingestion_checkpoints_job_id_fkey FOREIGN KEY (job_id) REFERENCES ingestion_jobs(id);
ALTER TABLE public.ingestion_jobs ADD CONSTRAINT ingestion_jobs_source_id_fkey FOREIGN KEY (source_id) REFERENCES ingestion_sources(id);
ALTER TABLE public.ingestion_sources ADD CONSTRAINT ingestion_active_job_fk FOREIGN KEY (id, active_job_id) REFERENCES ingestion_jobs(source_id, id);
ALTER TABLE public.ingestion_sources ADD CONSTRAINT ingestion_latest_job_fk FOREIGN KEY (id, latest_job_id) REFERENCES ingestion_jobs(source_id, id);
ALTER TABLE public.ingestion_sources ADD CONSTRAINT ingestion_sources_course_id_fkey FOREIGN KEY (course_id) REFERENCES courses(id);
ALTER TABLE public.ingestion_sources ADD CONSTRAINT ingestion_sources_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id);
ALTER TABLE public.lab_quizzes ADD CONSTRAINT lab_quizzes_job_id_fkey FOREIGN KEY (job_id) REFERENCES ingestion_jobs(id);
CREATE OR REPLACE FUNCTION public.ingestion_checkpoint(p_job_id uuid, p_lease_token uuid, p_stage integer, p_output jsonb, p_review_items jsonb DEFAULT '[]'::jsonb)
 RETURNS ingestion_jobs
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare j public.ingestion_jobs; saved jsonb;
begin
  select * into j from public.ingestion_jobs where id=p_job_id for update;
  if not found or j.status<>'PROCESSING' or j.lease_token is distinct from p_lease_token or j.lease_until<=now()
    then raise exception 'STALE_LEASE'; end if;
  if p_stage is null or p_stage not between 1 and 5 or p_output is null or jsonb_typeof(p_output)<>'object'
    or p_review_items is null or jsonb_typeof(p_review_items)<>'array' then raise exception 'INVALID_CHECKPOINT'; end if;
  if p_stage<=j.last_completed_stage then
    select output into saved from public.ingestion_checkpoints where job_id=p_job_id and stage=p_stage;
    if saved is distinct from p_output then raise exception 'CHECKPOINT_CONFLICT'; end if;
    return j;
  end if;
  if p_stage<>j.last_completed_stage+1 then raise exception 'CHECKPOINT_OUT_OF_ORDER'; end if;
  if p_stage=1 and (p_output->>'file_hash') is distinct from j.file_hash then raise exception 'FILE_HASH_MISMATCH'; end if;
  insert into public.ingestion_checkpoints(job_id,stage,output) values(p_job_id,p_stage,p_output);
  update public.ingestion_jobs set last_completed_stage=p_stage,
    current_stage=(array['EXTRACTING','VALIDATING','INDEXING','QUIZ_GENERATING','PUBLISHING'])[p_stage],
    progress_percentage=(array[10,40,55,75,95])[p_stage],review_items=review_items||p_review_items,updated_at=now()
    where id=p_job_id returning * into j;
  return j;
end $function$
;
CREATE OR REPLACE FUNCTION public.ingestion_claim(p_worker_id text, p_lease_seconds integer DEFAULT 120)
 RETURNS SETOF ingestion_jobs
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
  if p_worker_id is null or length(btrim(p_worker_id)) not between 1 and 100
    or p_lease_seconds is null or p_lease_seconds not between 30 and 900 then
    raise exception 'INVALID_WORKER_OR_LEASE';
  end if;
  -- Expired claims consume the same bounded attempt budget as explicit failures.
  with exhausted as (
    select id from public.ingestion_jobs where attempt_count>=max_attempts and
      (status='PENDING' or (status='PROCESSING' and lease_until<=now()))
      order by created_at for update skip locked limit 100
  ) update public.ingestion_jobs j set status='FAILED',error_code='ATTEMPTS_EXHAUSTED',
    lease_token=null,lease_until=null,worker_id=null,finished_at=now(),updated_at=now()
    from exhausted e where j.id=e.id;
  return query
    with candidate as (
      select id from public.ingestion_jobs where attempt_count<max_attempts and
        ((status='PENDING' and available_at<=now()) or (status='PROCESSING' and lease_until<=now()))
        order by available_at,created_at,id for update skip locked limit 1
    ) update public.ingestion_jobs j set status='PROCESSING',worker_id=p_worker_id,
      lease_token=gen_random_uuid(),lease_until=now()+make_interval(secs=>p_lease_seconds),
      heartbeat_at=now(),attempt_count=attempt_count+1,started_at=coalesce(started_at,now()),
      error_code=null,error_message=null,finished_at=null,updated_at=now()
      from candidate c where j.id=c.id returning j.*;
end $function$
;
CREATE OR REPLACE FUNCTION public.ingestion_enqueue(p_source_id uuid, p_file_name text, p_file_path text, p_file_hash text, p_pipeline_version text, p_config jsonb DEFAULT '{}'::jsonb)
 RETURNS ingestion_jobs
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare j public.ingestion_jobs;
begin
  perform 1 from public.ingestion_sources where id=p_source_id for update;
  if not found then raise exception 'SOURCE_NOT_FOUND'; end if;
  insert into public.ingestion_jobs(source_id,file_name,file_path,file_hash,pipeline_version,config)
  values(p_source_id,p_file_name,p_file_path,lower(p_file_hash),p_pipeline_version,p_config)
  on conflict (source_id,file_hash,pipeline_version,config_hash) do nothing returning * into j;
  if found then
    update public.ingestion_sources set latest_job_id=j.id,updated_at=now() where id=p_source_id;
  else
    select * into strict j from public.ingestion_jobs where source_id=p_source_id
      and file_hash=lower(p_file_hash) and pipeline_version=p_pipeline_version and config=p_config;
  end if;
  return j;
end $function$
;
CREATE OR REPLACE FUNCTION public.ingestion_fail(p_job_id uuid, p_lease_token uuid, p_error_code text, p_error_message text DEFAULT NULL::text, p_retryable boolean DEFAULT true)
 RETURNS ingestion_jobs
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare j public.ingestion_jobs;
begin
  select * into j from public.ingestion_jobs where id=p_job_id for update;
  if not found or j.status<>'PROCESSING' or j.lease_token is distinct from p_lease_token or j.lease_until<=now()
    then raise exception 'STALE_LEASE'; end if;
  if p_error_code is null or length(p_error_code) not between 1 and 100 then raise exception 'INVALID_ERROR_CODE'; end if;
  update public.ingestion_jobs set
    status=case when p_retryable and attempt_count<max_attempts then 'PENDING' else 'FAILED' end,
    available_at=now()+make_interval(secs=>least(300,5*power(2,attempt_count-1)::integer)),
    error_code=p_error_code,error_message=left(p_error_message,2000),
    finished_at=case when p_retryable and attempt_count<max_attempts then null else now() end,
    lease_token=null,lease_until=null,worker_id=null,updated_at=now()
    where id=p_job_id returning * into j;
  return j;
end $function$
;
CREATE OR REPLACE FUNCTION public.ingestion_guard_result_write()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare j public.ingestion_jobs; required_stage integer;
begin
  if TG_OP='UPDATE' and (new.job_id<>old.job_id or new.id<>old.id) then raise exception 'IMMUTABLE_RESULT_ID'; end if;
  select * into j from public.ingestion_jobs where id=new.job_id for update;
  required_stage := case when TG_TABLE_NAME='course_vectors' then 4 else 5 end;
  if not found or j.status<>'PROCESSING' or j.lease_token is distinct from new.lease_token or j.lease_until<=now()
    then raise exception 'STALE_LEASE'; end if;
  if j.last_completed_stage<>required_stage-1 then raise exception 'RESULT_STAGE_NOT_OPEN'; end if;
  return new;
end $function$
;
CREATE OR REPLACE FUNCTION public.ingestion_heartbeat(p_job_id uuid, p_lease_token uuid, p_lease_seconds integer DEFAULT 120)
 RETURNS boolean
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
  if p_lease_seconds is null or p_lease_seconds not between 30 and 900 then raise exception 'INVALID_LEASE'; end if;
  update public.ingestion_jobs set heartbeat_at=now(),lease_until=now()+make_interval(secs=>p_lease_seconds),updated_at=now()
    where id=p_job_id and status='PROCESSING' and lease_token=p_lease_token and lease_until>now();
  return found;
end $function$
;
CREATE OR REPLACE FUNCTION public.ingestion_publish(p_job_id uuid, p_lease_token uuid, p_expected_vectors integer, p_expected_concept_quizzes integer, p_expected_lab_quizzes integer)
 RETURNS ingestion_jobs
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare j public.ingestion_jobs; s public.ingestion_sources; nv integer; nc integer; nl integer;
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
  update public.ingestion_jobs set
    status=case when s.latest_job_id is distinct from p_job_id then 'SUPERSEDED'
      when jsonb_array_length(review_items)>0 then 'PARTIAL_SUCCESS' else 'COMPLETED' end,
    current_stage='DONE',last_completed_stage=6,progress_percentage=100,
    result=jsonb_build_object('vectors',nv,'concept_quizzes',nc,'lab_quizzes',nl,'published',s.latest_job_id=p_job_id),
    lease_token=null,lease_until=null,worker_id=null,finished_at=now(),updated_at=now()
    where id=p_job_id returning * into j;
  if s.latest_job_id=p_job_id then
    update public.ingestion_sources set active_job_id=p_job_id,updated_at=now() where id=s.id;
  end if;
  return j;
end $function$
;
CREATE TRIGGER concept_quizzes_write_guard BEFORE INSERT OR UPDATE ON public.concept_quizzes FOR EACH ROW EXECUTE FUNCTION ingestion_guard_result_write();
ALTER TABLE public.concept_quizzes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.concept_quizzes FROM PUBLIC;
GRANT ALL ON public.concept_quizzes TO service_role;
CREATE TRIGGER course_vectors_write_guard BEFORE INSERT OR UPDATE ON public.course_vectors FOR EACH ROW EXECUTE FUNCTION ingestion_guard_result_write();
ALTER TABLE public.course_vectors ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.course_vectors FROM PUBLIC;
GRANT ALL ON public.course_vectors TO service_role;
ALTER TABLE public.ingestion_checkpoints ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ingestion_checkpoints FROM PUBLIC;
GRANT ALL ON public.ingestion_checkpoints TO service_role;
ALTER TABLE public.ingestion_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ingestion_jobs FROM PUBLIC;
GRANT ALL ON public.ingestion_jobs TO service_role;
ALTER TABLE public.ingestion_sources ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ingestion_sources FROM PUBLIC;
GRANT ALL ON public.ingestion_sources TO service_role;
CREATE TRIGGER lab_quizzes_write_guard BEFORE INSERT OR UPDATE ON public.lab_quizzes FOR EACH ROW EXECUTE FUNCTION ingestion_guard_result_write();
ALTER TABLE public.lab_quizzes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.lab_quizzes FROM PUBLIC;
GRANT ALL ON public.lab_quizzes TO service_role;
REVOKE ALL ON FUNCTION public.ingestion_checkpoint FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.ingestion_checkpoint TO service_role;
REVOKE ALL ON FUNCTION public.ingestion_claim FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.ingestion_claim TO service_role;
REVOKE ALL ON FUNCTION public.ingestion_enqueue FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.ingestion_enqueue TO service_role;
REVOKE ALL ON FUNCTION public.ingestion_fail FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.ingestion_fail TO service_role;
REVOKE ALL ON FUNCTION public.ingestion_guard_result_write FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.ingestion_guard_result_write TO service_role;
REVOKE ALL ON FUNCTION public.ingestion_heartbeat FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.ingestion_heartbeat TO service_role;
REVOKE ALL ON FUNCTION public.ingestion_publish FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.ingestion_publish TO service_role;

