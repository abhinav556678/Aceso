
create table audit_log (
  id          bigserial primary key,
  at          timestamptz not null default now(),
  actor_id    uuid,
  actor_label text,
  actor_role  text,
  action      text not null,
  entity_type text not null, entity_id uuid, patient_id uuid,
  from_state  text, to_state text,
  payload     jsonb,
  prev_hash   text, row_hash text
);

create or replace function audit_chain() returns trigger language plpgsql as $$
declare last_hash text;
begin
  perform pg_advisory_xact_lock(727001);
  select row_hash into last_hash from audit_log order by id desc limit 1;
  new.prev_hash := coalesce(last_hash,'GENESIS');
  new.row_hash  := encode(extensions.digest(
      new.prev_hash || extract(epoch from new.at)::text || coalesce(new.actor_label,'') || new.action ||
      new.entity_type || coalesce(new.entity_id::text,'') || coalesce(new.payload::text,''),
      'sha256'),'hex');
  return new;
end $$;
create trigger audit_chain_t before insert on audit_log
  for each row execute function audit_chain();

create or replace function audit_immutable() returns trigger language plpgsql as $$
begin raise exception 'audit_log is append-only'; end $$;
create trigger audit_no_update before update or delete on audit_log
  for each row execute function audit_immutable();
create trigger audit_no_truncate before truncate on audit_log
  for each statement execute function audit_immutable();

create or replace function public.app_role() returns user_role
language sql stable security definer set search_path = public as
$$ select role from profiles where id = auth.uid() $$;

create or replace function facts_guard() returns trigger language plpgsql as $$
declare r user_role := public.app_role();
begin
  new.updated_at := now();
  if new.state is distinct from old.state then
    if not (
      (old.state='extracted' and new.state in ('verified','rejected')) or
      (old.state='verified'  and new.state in ('clinician_confirmed','rejected')) or
      (old.state='clinician_confirmed' and new.state='superseded') or
      (old.state in ('extracted','verified') and new.state='superseded')
    ) then
      raise exception 'Illegal fact transition % -> %', old.state, new.state;
    end if;
    if new.state='clinician_confirmed' and r is distinct from 'doctor' then
      raise exception 'Only a doctor can confirm a fact';
    end if;
  end if;
  return new;
end $$;
create trigger facts_guard_t before update on facts
  for each row execute function facts_guard();

create or replace function facts_audit() returns trigger language plpgsql as $$
declare v_from text := null; v_action text := 'fact.created';
begin
  if tg_op = 'UPDATE' then v_from := old.state::text; v_action := 'fact.state_change'; end if;
  insert into audit_log(actor_id, actor_label, actor_role, action, entity_type,
                        entity_id, patient_id, from_state, to_state, payload)
  values (auth.uid(),
          coalesce((select full_name from profiles where id=auth.uid()),
                   nullif(current_setting('app.actor', true),''), 'system:pipeline'),
          public.app_role()::text, v_action, 'fact', new.id, new.patient_id,
          v_from, new.state::text,
          jsonb_build_object('type',new.fact_type,'display',new.display,'assertion',new.assertion));
  return new;
end $$;
create trigger facts_audit_ins after insert on facts
  for each row execute function facts_audit();
create trigger facts_audit_upd after update of state on facts
  for each row when (old.state is distinct from new.state) execute function facts_audit();

create or replace function verify_audit_chain() returns table(ok boolean, broken_at bigint)
language plpgsql security definer as $$
declare r record; prev text := 'GENESIS'; h text;
begin
  for r in select * from audit_log order by id loop
    h := encode(extensions.digest(prev || extract(epoch from r.at)::text || coalesce(r.actor_label,'') || r.action ||
         r.entity_type || coalesce(r.entity_id::text,'') || coalesce(r.payload::text,''),'sha256'),'hex');
    if r.prev_hash is distinct from prev or r.row_hash is distinct from h then
      return query select false, r.id; return; end if;
    prev := r.row_hash;
  end loop;
  return query select true, null::bigint;
end $$;
