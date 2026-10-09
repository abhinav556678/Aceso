import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from aceso.main import app

@pytest.fixture
def mock_db():
    with patch('aceso.routes.patient.pool') as mock_pool:
        mock_conn = MagicMock()
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        yield mock_cur

def test_patient_timeline(mock_db):
    mock_db.fetchall.return_value = [
        ("evt1", None, "fact", "lab_result", "HbA1c", "HbA1c is 7.2", 7.2, "%", "verified")
    ]
    
    with TestClient(app) as client:
        response = client.get("/api/patients/p123/timeline")
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert len(data["events"]) == 1

def test_patient_trends(mock_db):
    mock_db.fetchall.side_effect = [
        [(None, 7.2, "%")], # labs
        [(None, "Metformin", "verified", {"duration_days": 30})] # meds
    ]
    
    with TestClient(app) as client:
        response = client.get("/api/patients/p123/trends?concept=HbA1c")
        assert response.status_code == 200
        data = response.json()
        assert len(data["labs"]) == 1
        assert len(data["meds"]) == 1
        assert data["meds"][0]["end_date"] is None # start_date is None, so end_date is None

def test_patient_summary(mock_db):
    mock_db.fetchone.return_value = ("Test Patient", None, "M")
    mock_db.fetchall.side_effect = [
        [("Diabetes",)], # conditions
        [("Metformin",)], # meds
        [("Penicillin",)] # allergies
    ]
    
    with TestClient(app) as client:
        response = client.get("/api/patients/p123/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Patient"
        assert "Diabetes" in data["active_conditions"]
