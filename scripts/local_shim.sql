-- Makes a plain Postgres look enough like Supabase for the migrations to apply:
-- the auth/extensions schemas, the API roles and auth.uid(). Used only by the
-- embedded local database (scripts/local_db.py) and the test suite.
create schema if not exists extensions;
create schema if not exists auth;

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin; end if;
end $$;

create table if not exists auth.users (
  instance_id uuid, id uuid primary key, aud text, role text, email text unique,
  encrypted_password text, email_confirmed_at timestamptz,
  raw_app_meta_data jsonb, raw_user_meta_data jsonb,
  created_at timestamptz, updated_at timestamptz,
  confirmation_token text, email_change text, email_change_token_new text, recovery_token text
);

create or replace function auth.uid() returns uuid language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
  )::uuid
$$;

-- The embedded Postgres has no pgcrypto; provide the three functions the schema uses.
create or replace function extensions.digest(data text, algo text) returns bytea language sql immutable as
  $$ select sha256(convert_to(data, 'UTF8')) $$;
create or replace function extensions.gen_salt(algo text) returns text language sql as $$ select 'local' $$;
create or replace function extensions.crypt(password text, salt text) returns text language sql as
  $$ select 'local-demo-no-login' $$;
