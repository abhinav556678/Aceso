import pytest
import uuid
from datetime import date
from unittest.mock import patch, MagicMock
from aceso.safety.engine import evaluate_patient_safety, calculate_egfr

def test_calculate_egfr():
    # Test values using CKD-EPI 2021
    # Example: 50 yr old Female, Scr 2.1
    # kappa = 0.7, alpha = -0.241
    # min = 1.0 (since 2.1/0.7 = 3.0), max = 3.0
    # 142 * (1.0)^-0.241 * (3.0)^-1.2 * 0.9938^50 * 1.012 = 28.2
    assert abs(calculate_egfr(2.1, 50, 'F') - 28.2) < 0.5

@patch('aceso.safety.engine.pool')
def test_evaluate_patient_safety_alert_fired(mock_pool):
    mock_conn = MagicMock()
    mock_pool.connection.return_value.__enter__.return_value = mock_conn
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Mocks for get_patient_health_data
    scr_id = uuid.uuid4()
    metformin_id = uuid.uuid4()
    
    def fetchone_side_effect():
        yield (date(1960, 1, 1), 'M')
        # for saving alerts loop, existing = None
        while True:
            yield None

    mock_cur.fetchone.side_effect = fetchone_side_effect()
    
    # 1st query: facts. Return 13 cols.
    # SELECT id, fact_type, display, value_num, unit, code, code_system, state, created_at, assertion, raw_text, dose, encounter_id
    mock_cur.fetchall.side_effect = [
        # Facts
        [
            (scr_id, 'lab_result', 'Creatinine', 3.0, 'mg/dL', '2160-0', 'LOINC', 'verified', date(2026,1,1), 'present', '3.0', None, 'e1'),
            (metformin_id, 'medication', 'Metformin 500mg', None, None, 'metformin', 'RxNorm', 'verified', date(2026,1,1), 'present', 'Metformin', None, 'e1')
        ],
        [], # allergy conflicts
        [], # interactions
        [], # duplicate therapy
        []  # dose warnings
    ]

    evaluate_patient_safety('patient-123', 'encounter-456')

    # Verify that save_alerts was called with KDIGO alert
    insert_call = [call for call in mock_cur.execute.call_args_list if "INSERT INTO safety_alerts" in call[0][0]]
    assert len(insert_call) == 1
    params = insert_call[0][0][1]
    assert params[3] == 'KDIGO-METFORMIN-EGFR30'
    assert params[4] == 'critical'
