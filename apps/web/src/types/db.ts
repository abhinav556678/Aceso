export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export interface Database {
  public: {
    Tables: {
      patients: {
        Row: {
          id: string
          mrn: string
          full_name: string
          dob: string
          sex: string
          phone: string | null
          abha_id: string | null
          preferred_lang: string | null
          created_at: string
        }
      }
      encounters: {
        Row: {
          id: string
          patient_id: string
          doctor_id: string | null
          started_at: string
          ended_at: string | null
          status: string
          chief_complaint: string | null
        }
      }
      facts: {
        Row: {
          id: string
          patient_id: string
          encounter_id: string | null
          fact_type: 'allergy' | 'medication' | 'lab_result' | 'diagnosis' | 'vital' | 'symptom' | 'history' | 'plan_item'
          assertion: 'present' | 'denied' | 'uncertain'
          code_system: string | null
          code: string | null
          display: string
          raw_text: string | null
          value_num: number | null
          value_text: string | null
          unit: string | null
          dose: Json | null
          effective_at: string | null
          state: 'extracted' | 'verified' | 'clinician_confirmed' | 'rejected' | 'superseded'
          confidence: number | null
          confidence_parts: Json | null
          needs_attention: boolean | null
          attention_reasons: string[] | null
          superseded_by: string | null
          source: 'audio' | 'document' | 'manual'
          recording_id: string | null
          segment_ids: string[] | null
          audio_start_ms: number | null
          audio_end_ms: number | null
          document_id: string | null
          block_ids: string[] | null
          page_no: number | null
          bbox: Json | null
          verification: Json | null
          created_by: string | null
          created_at: string | null
          updated_at: string | null
        }
      }
      profiles: {
        Row: {
          id: string
          full_name: string
          role: 'doctor' | 'nurse' | 'admin'
          registration_no: string | null
          preferred_lang: string | null
          created_at: string | null
        }
      }
    }
  }
}
