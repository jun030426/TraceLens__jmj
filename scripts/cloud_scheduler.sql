-- Run once in Supabase SQL Editor AFTER deployment/migrations and Vault configuration.
-- Vault secrets: lerny_tick_url (https://YOUR_DOMAIN/api/internal/jobs/tick),
-- lerny_cron_secret (same as Vercel CRON_SECRET).
-- For protected Vercel deployments also set lerny_vercel_bypass.
-- This scheduler runs in Supabase, independently of the test PC and Vercel Hobby cron limits.
create extension if not exists pg_cron;
create extension if not exists pg_net;

do $$
begin
  if not exists (select 1 from vault.decrypted_secrets where name = 'lerny_tick_url')
     or not exists (select 1 from vault.decrypted_secrets where name = 'lerny_cron_secret') then
    raise exception 'Configure lerny_tick_url and lerny_cron_secret in Vault first';
  end if;
end $$;

select cron.schedule(
  'lerny-cloud-jobs', '* * * * *',
  $cron$
  select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'lerny_tick_url'),
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'lerny_cron_secret')
    ) || case when exists(select 1 from vault.decrypted_secrets where name = 'lerny_vercel_bypass')
      then jsonb_build_object('x-vercel-protection-bypass',
        (select decrypted_secret from vault.decrypted_secrets where name = 'lerny_vercel_bypass'))
      else '{}'::jsonb end,
    body := '{}'::jsonb,
    timeout_milliseconds := 250000
  );
  $cron$
);
