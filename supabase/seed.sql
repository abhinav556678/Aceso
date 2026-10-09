-- auth.users requires a few fields
insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, recovery_sent_at, last_sign_in_at, raw_app_meta_data, raw_user_meta_data, created_at, updated_at, confirmation_token, email_change, email_change_token_new, recovery_token)
values
  ('00000000-0000-0000-0000-000000000000', 'u0000000-0000-4000-8000-000000000001', 'authenticated', 'authenticated', 'dr.rao@aceso.demo', crypt('password123', gen_salt('bf')), now(), now(), now(), '{"provider":"email","providers":["email"]}', '{}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', 'u0000000-0000-4000-8000-000000000002', 'authenticated', 'authenticated', 'nurse.priya@aceso.demo', crypt('password123', gen_salt('bf')), now(), now(), now(), '{"provider":"email","providers":["email"]}', '{}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', 'u0000000-0000-4000-8000-000000000003', 'authenticated', 'authenticated', 'admin.kumar@aceso.demo', crypt('password123', gen_salt('bf')), now(), now(), now(), '{"provider":"email","providers":["email"]}', '{}', now(), now(), '', '', '', '')
on conflict (id) do nothing;

insert into auth.identities (id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at)
values
  (gen_random_uuid(), 'u0000000-0000-4000-8000-000000000001', format('{"sub":"%s","email":"%s"}', 'u0000000-0000-4000-8000-000000000001', 'dr.rao@aceso.demo')::jsonb, 'email', now(), now(), now()),
  (gen_random_uuid(), 'u0000000-0000-4000-8000-000000000002', format('{"sub":"%s","email":"%s"}', 'u0000000-0000-4000-8000-000000000002', 'nurse.priya@aceso.demo')::jsonb, 'email', now(), now(), now()),
  (gen_random_uuid(), 'u0000000-0000-4000-8000-000000000003', format('{"sub":"%s","email":"%s"}', 'u0000000-0000-4000-8000-000000000003', 'admin.kumar@aceso.demo')::jsonb, 'email', now(), now(), now())
on conflict do nothing;

insert into profiles (id, full_name, role, registration_no, preferred_lang)
values
  ('u0000000-0000-4000-8000-000000000001', 'Dr. Rao', 'doctor', 'MCI-12345', 'en'),
  ('u0000000-0000-4000-8000-000000000002', 'Nurse Priya', 'nurse', null, 'en'),
  ('u0000000-0000-4000-8000-000000000003', 'Admin Kumar', 'admin', null, 'en')
on conflict (id) do nothing;

insert into drug_brands(brand,generic,rxnorm,atc,default_strength) values
 ('glycomet','metformin','6809','A10BA02','500 mg'),
 ('dolo 650','paracetamol','161','N02BE01','650 mg'),
 ('crocin','paracetamol','161','N02BE01','650 mg'),
 ('ecosprin','aspirin','1191','B01AC06','75 mg'),
 ('warf','warfarin','11289','B01AA03',null),
 ('mox','amoxicillin','723','J01CA04','500 mg'),
 ('augmentin','amoxicillin+clavulanate',null,'J01CR02','625 mg'),
 ('septran','co-trimoxazole','10180','J01EE01',null),
 ('telma','telmisartan','73494','C09CA07','40 mg'),
 ('pantocid','pantoprazole','40790','A02BC02','40 mg'),
 ('amaryl','glimepiride','25789','A10BB12','1 mg')
on conflict (brand) do update set generic=excluded.generic;

insert into concepts(system,code,display,synonyms) values
 ('LOINC','2160-0','Creatinine [Mass/volume] in Serum or Plasma','{creatinine,s.creatinine,scr}'),
 ('LOINC','4548-4','Hemoglobin A1c/Hemoglobin.total in Blood','{hba1c,a1c,glycated hemoglobin}'),
 ('LOINC','1558-6','Fasting glucose [Mass/volume] in Serum or Plasma','{fbs,fasting blood sugar}'),
 ('LOINC','718-7','Hemoglobin [Mass/volume] in Blood','{hb,haemoglobin}'),
 ('LOINC','2823-3','Potassium [Moles/volume] in Serum or Plasma','{k,potassium}'),
 ('LOINC','62238-1','eGFR (CKD-EPI) — computed','{egfr}'),
 ('LOINC','8480-6','Systolic blood pressure','{sbp,bp systolic}'),
 ('LOINC','8462-4','Diastolic blood pressure','{dbp,bp diastolic}'),
 ('ICD10','E11','Type 2 diabetes mellitus','{t2dm,diabetes,sugar}'),
 ('ICD10','N18.4','Chronic kidney disease, stage 4','{ckd 4}'),
 ('ICD10','I10','Essential hypertension','{htn,bp}'),
 ('ICD10','J06.9','Acute upper respiratory infection, unspecified','{uri,cold}')
on conflict do nothing;

insert into allergy_groups values
 ('penicillins','penicillin'),('penicillins','amoxicillin'),('penicillins','ampicillin'),
 ('penicillins','amoxicillin+clavulanate'),
 ('sulfonamide_antibiotics','sulfamethoxazole'),('sulfonamide_antibiotics','co-trimoxazole')
on conflict do nothing;

insert into reference_ranges(loinc,sex,age_min,age_max,low,high,plausible_min,plausible_max,unit) values
 ('2160-0','M',18,120,0.7,1.3,0.1,20,'mg/dL'),
 ('2160-0','F',18,120,0.6,1.1,0.1,20,'mg/dL'),
 ('4548-4','any',0,120,4.0,5.6,3,20,'%'),
 ('1558-6','any',0,120,70,100,20,800,'mg/dL')
on conflict do nothing;

insert into drug_interactions(drug_a,drug_b,severity,description,source,source_ref) values
 ('aspirin','warfarin','major','Increased bleeding risk','SEED-CURATED','manual-001')
on conflict do nothing;

insert into dose_limits(generic,route,population,max_single_mg,max_daily_mg,source) values
 ('paracetamol','PO','adult',1000,4000,'SEED-CURATED label limit'),
 ('metformin','PO','adult',1000,2550,'SEED-CURATED label limit')
on conflict do nothing;

insert into safety_rules (id, title, rule_type, guideline_source, severity, rule, clinician_reviewed_by) values
 ('KDIGO-METFORMIN-EGFR30', 'Metformin is contraindicated when eGFR < 30', 'lab_contraindication', 'KDIGO', 'critical',
  '{"all": [{"fact": {"type": "medication", "generic": "metformin", "assertion": "present"}}, {"metric": "egfr", "op": "<", "value": 30}]}',
  'Dr. Demo')
on conflict do nothing;

insert into patients(id,mrn,full_name,dob,sex,preferred_lang) values
 ('00000000-0000-4000-8000-000000000001','ACE-0001','Meena Rajan',        current_date - interval '50 years','F','ta'),
 ('00000000-0000-4000-8000-000000000002','ACE-0002','Arjun Menon',        current_date - interval '45 years','M','en'),
 ('00000000-0000-4000-8000-000000000003','ACE-0003','Lakshmi Narayanan',  current_date - interval '58 years','F','ta'),
 ('00000000-0000-4000-8000-000000000004','ACE-0004','Suresh Babu',        current_date - interval '72 years','M','ta'),
 ('00000000-0000-4000-8000-000000000005','ACE-0005','Fatima Begum',       current_date - interval '55 years','F','ta'),
 ('00000000-0000-4000-8000-000000000006','ACE-0006','Karthik S',          current_date - interval '34 years','M','en')
on conflict (id) do nothing;

-- S1 Golden Data
insert into encounters (id, patient_id, doctor_id, status) values
  ('e0000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000001', 'u0000000-0000-4000-8000-000000000001', 'in_progress')
on conflict do nothing;

insert into source_documents(id,patient_id,storage_path,kind,doc_date,page_count,ocr_engine,status) values
 ('d0000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000001',
  'documents/S1/labs_2026.pdf','lab_pdf', current_date - 14, 1,'golden','done')
on conflict do nothing;

insert into ocr_blocks(id,document_id,page_no,block_idx,kind,text,confidence,x,y,w,h) values
 ('b0000000-0000-4000-8000-000000000001','d0000000-0000-4000-8000-000000000001',1,12,'table_cell','2.1',0.97,0.52,0.31,0.06,0.022)
on conflict do nothing;

insert into audio_recordings (id, encounter_id, storage_path, duration_ms, status) values
 ('a0000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000001', 'audio/S1/visit.wav', 120000, 'done')
on conflict do nothing;

insert into transcript_segments (id, recording_id, seq, speaker, start_ms, end_ms, text, confidence) values
 ('t0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000001', 1, 'doctor', 41200, 44800, 'Continue Glycomet 500 twice daily.', 0.99)
on conflict do nothing;

insert into facts(id,patient_id,encounter_id,fact_type,assertion,code_system,code,display,raw_text,
                  value_num,unit,effective_at,state,confidence,confidence_parts,
                  source,document_id,block_ids,page_no,bbox,verification) values
 ('f0000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000001','e0000000-0000-4000-8000-000000000001',
  'lab_result','present','LOINC','2160-0','Creatinine, serum','2.1',
  2.1,'mg/dL', now() - interval '14 days','verified',0.96,
  '{"ocr":0.97,"plausibility":1,"verification":1}',
  'document','d0000000-0000-4000-8000-000000000001','{b0000000-0000-4000-8000-000000000001}',
  1,'{"x":0.52,"y":0.31,"w":0.06,"h":0.022}',
  '{"ocr_match":{"ok":true},"transcript_support":{"ok":null},"omission":{"ok":true}}'),
 ('f0000000-0000-4000-8000-000000000002','00000000-0000-4000-8000-000000000001','e0000000-0000-4000-8000-000000000001',
  'medication','present','RxNorm','6809','Metformin','Glycomet 500',
  null,null, now(),'extracted',0.85,
  '{"verification":1}',
  'audio',null,null,null,null,
  '{"transcript_support":{"ok":true},"omission":{"ok":true}}')
on conflict (id) do nothing;

update facts set recording_id = 'a0000000-0000-4000-8000-000000000001', segment_ids = '{t0000000-0000-4000-8000-000000000001}', audio_start_ms = 41200, audio_end_ms = 44800 where id = 'f0000000-0000-4000-8000-000000000002';

insert into safety_alerts (id, patient_id, encounter_id, rule_id, severity, message, status, trigger_fact_ids, trace) values
 ('al000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000001', 'e0000000-0000-4000-8000-000000000001', 'KDIGO-METFORMIN-EGFR30', 'critical', 'Metformin is contraindicated when eGFR < 30 mL/min/1.73 m²', 'open', '{f0000000-0000-4000-8000-000000000001,f0000000-0000-4000-8000-000000000002}', '{"steps": [{"label": "Medication on list", "result": true, "fact_id": "f0000000-0000-4000-8000-000000000002"}, {"label": "Computed eGFR", "value": 28.2, "unit": "mL/min/1.73 m\u00b2"}], "conclusion": "Metformin is contraindicated when eGFR < 30"}')
on conflict do nothing;

