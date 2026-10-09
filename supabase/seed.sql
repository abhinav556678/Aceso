-- Reference data + demo users + the six synthetic patients. Safe to re-run.
-- Clinical demo data (documents, transcripts, facts) is created by scripts/seed_demo.py,
-- because it needs real PDF bounding boxes.
-- All data is fictional. Clinical content must be reviewed by a clinician before real use.

-- ---------- demo users (API uses a demo role switcher, not Supabase login) ----------
insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
                        raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
                        confirmation_token, email_change, email_change_token_new, recovery_token)
select '00000000-0000-0000-0000-000000000000', v.id::uuid, 'authenticated', 'authenticated', v.email,
       extensions.crypt('password123', extensions.gen_salt('bf')), now(),
       '{"provider":"email","providers":["email"]}', '{}', now(), now(), '', '', '', ''
from (values
  ('aaaaaaaa-0000-4000-8000-000000000001','dr.rao@aceso.demo'),
  ('aaaaaaaa-0000-4000-8000-000000000002','nurse.priya@aceso.demo'),
  ('aaaaaaaa-0000-4000-8000-000000000003','admin.kumar@aceso.demo')
) as v(id, email)
where not exists (select 1 from auth.users u where u.email = v.email);

insert into profiles (id, full_name, role, registration_no, preferred_lang)
select u.id, v.full_name, v.role::user_role, v.reg, 'en'
from (values
  ('dr.rao@aceso.demo','Dr. Rao','doctor','TNMC-DEMO-12345'),
  ('nurse.priya@aceso.demo','Nurse Priya','nurse',null),
  ('admin.kumar@aceso.demo','Admin Kumar','admin',null)
) as v(email, full_name, role, reg)
join auth.users u on u.email = v.email
on conflict (id) do nothing;

-- ---------- terminology ----------
-- brand (or generic spelled out) -> generic. Lower-case keys.
insert into drug_brands(brand,generic,rxnorm,atc,default_strength) values
 ('glycomet','metformin','6809','A10BA02','500 mg'),
 ('metformin','metformin','6809','A10BA02',null),
 ('dolo','paracetamol','161','N02BE01','650 mg'),
 ('crocin','paracetamol','161','N02BE01','650 mg'),
 ('calpol','paracetamol','161','N02BE01','500 mg'),
 ('paracetamol','paracetamol','161','N02BE01',null),
 ('acetaminophen','paracetamol','161','N02BE01',null),
 ('ecosprin','aspirin','1191','B01AC06','75 mg'),
 ('aspirin','aspirin','1191','B01AC06',null),
 ('warf','warfarin','11289','B01AA03',null),
 ('warfarin','warfarin','11289','B01AA03',null),
 ('mox','amoxicillin','723','J01CA04','500 mg'),
 ('amoxicillin','amoxicillin','723','J01CA04',null),
 ('augmentin','amoxicillin+clavulanate',null,'J01CR02','625 mg'),
 ('penicillin','penicillin','7980','J01CE',null),
 ('ampicillin','ampicillin','733','J01CA01',null),
 ('septran','co-trimoxazole','10180','J01EE01',null),
 ('co-trimoxazole','co-trimoxazole','10180','J01EE01',null),
 ('cotrimoxazole','co-trimoxazole','10180','J01EE01',null),
 ('telma','telmisartan','73494','C09CA07','40 mg'),
 ('telmisartan','telmisartan','73494','C09CA07',null),
 ('pantocid','pantoprazole','40790','A02BC02','40 mg'),
 ('pantoprazole','pantoprazole','40790','A02BC02',null),
 ('amaryl','glimepiride','25789','A10BB12','1 mg'),
 ('glimepiride','glimepiride','25789','A10BB12',null),
 ('brufen','ibuprofen','5640','M01AE01','400 mg'),
 ('ibuprofen','ibuprofen','5640','M01AE01',null)
on conflict (brand) do update set generic=excluded.generic, rxnorm=excluded.rxnorm,
  atc=excluded.atc, default_strength=excluded.default_strength;

insert into concepts(system,code,display,synonyms) values
 ('LOINC','2160-0','Creatinine, serum','{creatinine,s.creatinine,serum creatinine,scr}'),
 ('LOINC','4548-4','HbA1c','{hba1c,a1c,glycated hemoglobin,glycosylated hemoglobin}'),
 ('LOINC','1558-6','Fasting glucose','{fbs,fasting blood sugar,fasting glucose,fasting plasma glucose}'),
 ('LOINC','718-7','Hemoglobin','{hemoglobin,haemoglobin}'),
 ('LOINC','2823-3','Potassium','{potassium,serum potassium}'),
 ('LOINC','62238-1','eGFR (CKD-EPI 2021)','{egfr}'),
 ('LOINC','8480-6','Systolic blood pressure','{sbp,systolic bp,systolic blood pressure}'),
 ('LOINC','8462-4','Diastolic blood pressure','{dbp,diastolic bp,diastolic blood pressure}'),
 ('LOINC','8867-4','Heart rate','{heart rate,pulse}'),
 ('LOINC','29463-7','Body weight','{weight,body weight}'),
 ('ICD10','E11','Type 2 diabetes mellitus','{t2dm,type 2 diabetes,type 2 diabetes mellitus,diabetes,diabetes mellitus}'),
 ('ICD10','N18.4','Chronic kidney disease, stage 4','{ckd stage 4,ckd 4}'),
 ('ICD10','N18.9','Chronic kidney disease','{ckd,chronic kidney disease}'),
 ('ICD10','I10','Essential hypertension','{htn,hypertension,high blood pressure}'),
 ('ICD10','I48.91','Atrial fibrillation','{atrial fibrillation,afib}'),
 ('ICD10','M19.90','Osteoarthritis','{osteoarthritis}'),
 ('ICD10','J06.9','Acute upper respiratory infection','{uri,urti,upper respiratory infection,viral uri,common cold}')
on conflict (system,code) do update set display=excluded.display, synonyms=excluded.synonyms;

insert into allergy_groups values
 ('penicillins','penicillin'),('penicillins','amoxicillin'),('penicillins','ampicillin'),
 ('penicillins','amoxicillin+clavulanate'),
 ('sulfonamide_antibiotics','sulfa'),('sulfonamide_antibiotics','sulfonamide'),
 ('sulfonamide_antibiotics','sulfamethoxazole'),('sulfonamide_antibiotics','co-trimoxazole')
on conflict do nothing;

insert into reference_ranges(loinc,sex,age_min,age_max,low,high,plausible_min,plausible_max,unit) values
 ('2160-0','M',18,120,0.7,1.3,0.1,20,'mg/dL'),
 ('2160-0','F',18,120,0.6,1.1,0.1,20,'mg/dL'),
 ('4548-4','any',0,120,4.0,5.6,3,20,'%'),
 ('1558-6','any',0,120,70,100,20,800,'mg/dL'),
 ('718-7','any',0,120,12,16,3,25,'g/dL'),
 ('2823-3','any',0,120,3.5,5.1,1.5,9,'mmol/L'),
 ('62238-1','any',0,120,90,120,1,200,'mL/min/1.73m2'),
 ('8480-6','any',0,120,90,130,50,280,'mmHg'),
 ('8462-4','any',0,120,60,85,30,180,'mmHg'),
 ('8867-4','any',0,120,60,100,25,250,'/min'),
 ('29463-7','any',0,120,null,null,2,400,'kg')
on conflict do nothing;

-- ---------- safety knowledge ----------
insert into drug_interactions(drug_a,drug_b,severity,description,source,source_ref) values
 ('aspirin','warfarin','major','Increased bleeding risk','SEED-CURATED','manual-001')
on conflict do nothing;

insert into dose_limits(generic,route,population,max_single_mg,max_daily_mg,source) values
 ('paracetamol','PO','adult',1000,4000,'SEED-CURATED label limit'),
 ('metformin','PO','adult',1000,2550,'SEED-CURATED label limit')
on conflict do nothing;

-- Rules are data; services/api/aceso/safety/engine.py evaluates them.
insert into safety_rules (id, title, rule_type, guideline_source, severity, rule, clinician_reviewed_by) values
 ('KDIGO-METFORMIN-EGFR30', 'Metformin is contraindicated when eGFR < 30', 'lab_contraindication',
  'KDIGO guideline (metformin in CKD) · metformin product labelling', 'critical',
  '{"all":[{"fact":{"type":"medication","generic":"metformin","assertion":"present"}},{"metric":"egfr","op":"<","value":30}],"message":"Metformin is contraindicated when eGFR < 30 mL/min/1.73 m²"}',
  null),
 ('INT-PAIR', 'Drug-drug interaction', 'interaction', 'drug_interactions table (SEED-CURATED)', 'high',
  '{"min_severity":"moderate"}', null),
 ('DUP-THERAPY', 'Duplicate therapy', 'duplicate', 'Same generic prescribed under two products', 'moderate',
  '{}', null),
 ('DOSE-MAX-DAILY', 'Maximum daily dose exceeded', 'dose', 'dose_limits table (SEED-CURATED label limits)', 'high',
  '{}', null),
 ('ALLERGY-CONFLICT', 'Prescribed drug conflicts with a recorded allergy', 'allergy',
  'allergy_groups cross-reactivity table', 'critical', '{}', null),
 ('RECORD-CONTRADICTION', 'The record contradicts itself', 'contradiction',
  'Fact store consistency check', 'high', '{}', null)
on conflict (id) do update set title=excluded.title, rule_type=excluded.rule_type,
  guideline_source=excluded.guideline_source, severity=excluded.severity, rule=excluded.rule;

-- ---------- synthetic patients: six planted scenarios (1-6) and nine background charts (7-15) ----------
insert into patients(id,mrn,full_name,dob,sex,preferred_lang) values
 ('00000000-0000-4000-8000-000000000001','ACE-0001','Meena Rajan',        (current_date - interval '50 years 2 months')::date,'F','ta'),
 ('00000000-0000-4000-8000-000000000002','ACE-0002','Arjun Menon',        (current_date - interval '45 years 2 months')::date,'M','en'),
 ('00000000-0000-4000-8000-000000000003','ACE-0003','Lakshmi Narayanan',  (current_date - interval '58 years 2 months')::date,'F','ta'),
 ('00000000-0000-4000-8000-000000000004','ACE-0004','Suresh Babu',        (current_date - interval '72 years 2 months')::date,'M','ta'),
 ('00000000-0000-4000-8000-000000000005','ACE-0005','Fatima Begum',       (current_date - interval '55 years 2 months')::date,'F','hi'),
 ('00000000-0000-4000-8000-000000000006','ACE-0006','Karthik S',          (current_date - interval '34 years 2 months')::date,'M','en'),
 ('00000000-0000-4000-8000-000000000007','ACE-0007','Anitha Krishnan',    (current_date - interval '41 years 5 months')::date,'F','ta'),
 ('00000000-0000-4000-8000-000000000008','ACE-0008','Mohammed Irfan',     (current_date - interval '63 years 1 month')::date,'M','hi'),
 ('00000000-0000-4000-8000-000000000009','ACE-0009','Revathi Sundaram',   (current_date - interval '67 years 8 months')::date,'F','ta'),
 ('00000000-0000-4000-8000-000000000010','ACE-0010','Vikram Nair',        (current_date - interval '29 years 3 months')::date,'M','en'),
 ('00000000-0000-4000-8000-000000000011','ACE-0011','Deepa Iyer',         (current_date - interval '52 years 6 months')::date,'F','en'),
 ('00000000-0000-4000-8000-000000000012','ACE-0012','Ramesh Gupta',       (current_date - interval '70 years 4 months')::date,'M','hi'),
 ('00000000-0000-4000-8000-000000000013','ACE-0013','Sneha Pillai',       (current_date - interval '36 years 9 months')::date,'F','en'),
 ('00000000-0000-4000-8000-000000000014','ACE-0014','Joseph Mathew',      (current_date - interval '58 years 7 months')::date,'M','en'),
 ('00000000-0000-4000-8000-000000000015','ACE-0015','Nandini Shetty',     (current_date - interval '24 years 2 months')::date,'F','hi')
on conflict (id) do nothing;
