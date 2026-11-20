-- Additive server-only vector store for the integrated service and teammate CLI.
-- Existing course_vectors belongs to the ingestion lease workflow and is untouched.
begin;
create table public.rag_shared_embeddings (
    profile text not null check (length(profile) between 1 and 200),
    input_hash text not null check (input_hash ~ '^[0-9a-f]{64}$'),
    document_text text not null check (length(btrim(document_text)) > 0),
    document_title text not null,
    embedding_model text not null check (embedding_model = 'gemini-embedding-2'),
    embedding extensions.vector(768) not null check (extensions.vector_norm(embedding) > 0),
    created_at timestamptz not null default now(),
    primary key (profile, input_hash)
);
alter table public.rag_shared_embeddings enable row level security;
revoke all on public.rag_shared_embeddings from public, anon, authenticated;
grant select, insert, delete on public.rag_shared_embeddings to service_role;
create policy rag_backend_only on public.rag_shared_embeddings
    for all to service_role using (true) with check (true);

-- Candidate keys come only from material rows authorized by the backend.
-- Invoker functions deliberately grant no access to browser roles.
create function public.lerny_rag_fetch(p_profile text, p_keys text[], p_vectors boolean default true)
returns table(input_hash text, embedding text)
language sql stable security invoker set search_path = public, extensions
as $$
    select r.input_hash, case when p_vectors then r.embedding::text else null end
    from public.rag_shared_embeddings r
    where r.profile = p_profile and r.input_hash = any(p_keys)
      and cardinality(p_keys) between 1 and 200
    order by r.input_hash;
$$;
create function public.lerny_rag_match(p_profile text, p_keys text[], p_query extensions.vector, p_limit integer default 8)
returns table(input_hash text, score double precision)
language sql stable security invoker set search_path = public, extensions
as $$
    select r.input_hash, 1 - (r.embedding <=> p_query) as score
    from public.rag_shared_embeddings r
    where r.profile = p_profile and r.input_hash = any(p_keys)
      and cardinality(p_keys) between 1 and 200
      and vector_dims(p_query) = 768 and vector_norm(p_query) > 0
    order by r.embedding <=> p_query, r.input_hash
    limit least(greatest(p_limit, 1), 100);
$$;
revoke all on function public.lerny_rag_fetch(text,text[],boolean) from public, anon, authenticated;
revoke all on function public.lerny_rag_match(text,text[],extensions.vector,integer) from public, anon, authenticated;
grant execute on function public.lerny_rag_fetch(text,text[],boolean) to service_role;
grant execute on function public.lerny_rag_match(text,text[],extensions.vector,integer) to service_role;
notify pgrst, 'reload schema';
commit;
