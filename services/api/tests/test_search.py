import pytest
import uuid
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from aceso.main import app

client = TestClient(app)

@patch('aceso.routes.search.pool')
def test_search_facts(mock_pool):
    mock_conn = MagicMock()
    mock_pool.connection.return_value.__enter__.return_value = mock_conn
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    
    mock_cur.fetchall.return_value = [
        (
            uuid.uuid4(), uuid.uuid4(), "Patient is allergic to sulfa", 
            "Sulfa Allergy", "audio", 1000, 2000, None, None, 0.95, 0.85, "sulfa"
        )
    ]
    
    response = client.post(
        "/api/search",
        json={"query": "Does he have a sulfa allergy?", "patient_id": "p123"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["content"] == "Patient is allergic to sulfa"
    
    calls = mock_cur.execute.call_args_list
    assert len(calls) == 2 # 1 for search, 1 for audit
    assert "fact_chunks fc" in calls[0][0][0]
    assert "audit_log" in calls[1][0][0]
