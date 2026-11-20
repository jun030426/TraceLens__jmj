-- Apply after API/migration deployment. Independent of the EC2 worker being controlled.
-- Vault: lerny_ops_tick_url = https://YOUR_DOMAIN/api/internal/ops/tick
-- Reuse lerny_cron_secret. Optional lerny_vercel_bypass is server-side only.
create extension if not exists pg_cron;
create extension if not exists pg_net;
do $$ begin
  if not exists(select 1 from vault.decrypted_secrets where name = 'lerny_ops_tick_url')
     or not exists(select 1 from vault.decrypted_secrets where name = 'lerny_cron_secret') then
    raise exception 'Configure administrator scheduler Vault entries first';
  end if;
end $$;
select cron.schedule('lerny-admin-operations', '* * * * *', $cron$
  select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'lerny_ops_tick_url'),
    headers := jsonb_build_object('Content-Type', 'application/json', 'Authorization',
      'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'lerny_cron_secret'))
      || case when exists(select 1 from vault.decrypted_secrets where name = 'lerny_vercel_bypass')
      then jsonb_build_object('x-vercel-protection-bypass',
        (select decrypted_secret from vault.decrypted_secrets where name = 'lerny_vercel_bypass'))
      else '{}'::jsonb end,
    body := '{}'::jsonb, timeout_milliseconds := 50000);
$cron$);
