
do $$ declare t text; begin
  foreach t in array array['profiles','patients','encounters','audio_recordings',
   'transcript_segments','source_documents','ocr_blocks','facts','fact_chunks',
   'safety_alerts','soap_notes','note_edits','patient_exports','open_loops',
   'audit_log','jobs','eval_runs','eval_results'] loop
    execute format('alter table %I enable row level security', t);
  end loop; end $$;

create policy read_all on concepts           for select to authenticated using (true);
create policy read_all on drug_brands        for select to authenticated using (true);
create policy read_all on reference_ranges   for select to authenticated using (true);
create policy read_all on drug_interactions  for select to authenticated using (true);
create policy read_all on safety_rules       for select to authenticated using (true);
do $$ declare t text; begin
  foreach t in array array['concepts','drug_brands','allergy_groups','reference_ranges',
                           'drug_interactions','dose_limits','safety_rules'] loop
    execute format('alter table %I enable row level security', t);
  end loop; end $$;
create policy read_all on allergy_groups for select to authenticated using (true);
create policy read_all on dose_limits    for select to authenticated using (true);

create policy profiles_self on profiles for select to authenticated
  using (id = auth.uid() or public.app_role()='admin');

create policy patients_read on patients for select to authenticated using (public.app_role() is not null);
create policy patients_admin_write on patients for all to authenticated
  using (public.app_role()='admin') with check (public.app_role()='admin');

do $$ declare t text; begin
  foreach t in array array['encounters','audio_recordings','transcript_segments',
   'source_documents','ocr_blocks','facts','fact_chunks','safety_alerts','soap_notes',
   'note_edits','patient_exports','open_loops'] loop
    execute format($f$create policy clin_rw on %I for all to authenticated
      using (public.app_role() in ('doctor','nurse'))
      with check (public.app_role() in ('doctor','nurse'))$f$, t);
  end loop; end $$;

create policy audit_admin_read on audit_log for select to authenticated using (public.app_role()='admin');
