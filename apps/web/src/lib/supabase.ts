import { createClient } from '@supabase/supabase-js'
import { Database } from '../types/db'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://mock.supabase.co'
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || 'mock-key'

export const supabase = createClient<Database>(supabaseUrl, supabaseKey)

// Mock Data for the frontend so it works immediately
export const MOCK_DATA = {
  patients: [
    {
      id: '00000000-0000-4000-8000-000000000001',
      mrn: 'ACE-0001',
      full_name: 'Meena Rajan',
      dob: '1976-10-09',
      sex: 'F',
      phone: null,
      abha_id: null,
      preferred_lang: 'ta',
      created_at: new Date().toISOString()
    }
  ],
  facts: [
    {
      id: 'f0000000-0000-4000-8000-000000000001',
      patient_id: '00000000-0000-4000-8000-000000000001',
      encounter_id: 'e0000000-0000-4000-8000-000000000001',
      fact_type: 'lab_result',
      assertion: 'present',
      code_system: 'LOINC',
      code: '2160-0',
      display: 'Creatinine, serum',
      raw_text: '2.1',
      value_num: 2.1,
      value_text: null,
      unit: 'mg/dL',
      dose: null,
      effective_at: new Date(Date.now() - 14 * 86400000).toISOString(),
      state: 'verified',
      confidence: 0.96,
      confidence_parts: { ocr: 0.97, plausibility: 1, verification: 1 },
      needs_attention: false,
      attention_reasons: null,
      superseded_by: null,
      source: 'document',
      recording_id: null,
      segment_ids: null,
      audio_start_ms: null,
      audio_end_ms: null,
      document_id: 'd0000000-0000-4000-8000-000000000001',
      block_ids: ['b0000000-0000-4000-8000-000000000001'],
      page_no: 1,
      bbox: { x: 0.52, y: 0.31, w: 0.06, h: 0.022 },
      verification: { ocr_match: { ok: true }, transcript_support: { ok: null }, omission: { ok: true } },
      created_by: 'system:pipeline',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    {
      id: 'f0000000-0000-4000-8000-000000000002',
      patient_id: '00000000-0000-4000-8000-000000000001',
      encounter_id: 'e0000000-0000-4000-8000-000000000001',
      fact_type: 'medication',
      assertion: 'present',
      code_system: 'RxNorm',
      code: '6809',
      display: 'Metformin',
      raw_text: 'Glycomet 500',
      value_num: null,
      value_text: null,
      unit: null,
      dose: null,
      effective_at: new Date().toISOString(),
      state: 'extracted',
      confidence: 0.85,
      confidence_parts: { verification: 1 },
      needs_attention: false,
      attention_reasons: null,
      superseded_by: null,
      source: 'audio',
      recording_id: 'a0000000-0000-4000-8000-000000000001',
      segment_ids: ['t0000000-0000-4000-8000-000000000001'],
      audio_start_ms: 41200,
      audio_end_ms: 44800,
      document_id: null,
      block_ids: null,
      page_no: null,
      bbox: null,
      verification: { transcript_support: { ok: true }, omission: { ok: true } },
      created_by: 'system:pipeline',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
  ],
  safety_alerts: [
    {
      id: 'a0000000-0000-4000-8000-000000000001',
      patient_id: '00000000-0000-4000-8000-000000000001',
      rule_id: 'KDIGO-METFORMIN-EGFR30',
      severity: 'critical',
      message: 'Critical: Metformin is contraindicated with eGFR < 30 (Current eGFR: 28.5 mL/min/1.73m²)',
      status: 'open',
      trigger_fact_ids: ['f0000000-0000-4000-8000-000000000001', 'f0000000-0000-4000-8000-000000000002'],
      trace: {
        logic: "IF eGFR < 30 AND Medication = Metformin THEN Contraindicated",
        variables: {
          eGFR: 28.5,
          creatinine_value: 2.1,
          age: 50,
          sex: 'F'
        },
        steps: [
          "Identified verified serum creatinine: 2.1 mg/dL",
          "Computed eGFR using CKD-EPI 2021: 28.5 mL/min/1.73m²",
          "Detected active Metformin prescription",
          "Triggered KDIGO rule due to eGFR < 30"
        ]
      },
      created_at: new Date().toISOString()
    }
  ],
  soap_notes: [
    {
      id: 's0000000-0000-4000-8000-000000000001',
      encounter_id: 'e0000000-0000-4000-8000-000000000001',
      version: 1,
      subjective: [
        { text: "Patient reports no fever.", fact_ids: [] }
      ],
      objective: [
        { text: "Creatinine, serum is 2.1 mg/dL.", fact_ids: ["f0000000-0000-4000-8000-000000000001"] }
      ],
      assessment: [
        { text: "Type 2 Diabetes Mellitus with CKD.", fact_ids: [] }
      ],
      plan: [
        { text: "Prescribed Metformin.", fact_ids: ["f0000000-0000-4000-8000-000000000002"] }
      ],
      status: 'draft',
      generated_by: 'system'
    }
  ]
}
