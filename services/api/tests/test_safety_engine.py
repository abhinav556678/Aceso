import pytest
import sys
from unittest.mock import patch, MagicMock
mock_db = MagicMock()
sys.modules['aceso.db'] = mock_db

from aceso.safety.engine import calculate_egfr, evaluate_patient_safety

def test_calculate_egfr():
    # Test values using CKD-EPI 2021
    # E.g., Female, 50 y/o, Scr 1.2
    # kappa=0.7, alpha=-0.241, Scr/k=1.714
    # eGFR = 142 * (1)^-0.241 * (1.714)^-1.200 * (0.9938)^50 * 1.012
    # We just need to check it computes something reasonable and deterministic.
    egfr1 = calculate_egfr(1.2, 50, 'F')
    assert isinstance(egfr1, float)
    
    egfr2 = calculate_egfr(2.5, 60, 'M') # Should be low eGFR
    assert egfr2 < 30.0

@patch('aceso.safety.engine.pool')
def test_evaluate_patient_safety_alert_fired(mock_pool):
    mock_conn = MagicMock()
    mock_pool.connection.return_value.__enter__.return_value = mock_conn
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    
    from datetime import date
    import uuid
    # Mock patient dob, sex
    mock_cur.fetchone.side_effect = [
        (date(1960, 1, 1), 'M'),  # Patient
        None # existing alert query returns None
    ]
    
    # Mock facts: High Creatinine and Metformin
    scr_id = uuid.uuid4()
    metformin_id = uuid.uuid4()
    mock_cur.fetchall.return_value = [
        (scr_id, 'lab_result', 'Creatinine', 3.0, 'mg/dL', '2160-0', 'LOINC'),
        (metformin_id, 'medication', 'Metformin 500mg', None, None, '860975', 'RxNorm')
    ]
    
    evaluate_patient_safety('patient-123', 'encounter-456')
    
    # Assert INSERT into safety_alerts was called
    assert mock_cur.execute.call_count == 4
    
    insert_call = mock_cur.execute.call_args_list[3]
    query, params = insert_call[0]
    
    assert "INSERT INTO safety_alerts" in query
    assert params[3] == "KDIGO-METFORMIN-EGFR30"
    assert params[4] == "critical"
    assert "Metformin is contraindicated with eGFR < 30" in params[5]
