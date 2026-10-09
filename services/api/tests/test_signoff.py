import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from aceso.main import app

client = TestClient(app)

@pytest.fixture
def mock_pool():
    with patch("aceso.routes.signoff.pool") as mock:
        yield mock

def test_signoff_gating_fails_with_open_alerts(mock_pool):
    mock_conn = mock_pool.connection.return_value.__enter__.return_value
    mock_cur = mock_conn.cursor.return_value.__enter__.return_value
    
    # Mock open alerts
    mock_cur.fetchall.return_value = [("alert1",)]
    
    response = client.post(
        "/api/encounters/e123/signoff",
        json={"user_id": "u123"}
    )
    assert response.status_code == 400
    assert "Cannot sign off. There are unacknowledged safety alerts." in response.json()["detail"]

def test_signoff_success(mock_pool):
    mock_conn = mock_pool.connection.return_value.__enter__.return_value
    mock_cur = mock_conn.cursor.return_value.__enter__.return_value
    
    # 1. gating check passes
    mock_cur.fetchall.return_value = []
    
    # 2. note row fetched
    mock_cur.fetchone.return_value = ({"a":"1"}, {"b":"2"}, {"c":"3"}, {"d":"4"})
    
    response = client.post(
        "/api/encounters/e123/signoff",
        json={"user_id": "u123"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    
    # Verify transaction calls
    calls = mock_cur.execute.call_args_list
    # First is the SELECT for safety alerts
    assert "SELECT id FROM safety_alerts" in calls[0][0][0]
    
    # Let's just check the presence of the others
    queries = [call[0][0] for call in calls]
    assert any("UPDATE facts" in q for q in queries)
    assert any("UPDATE soap_notes" in q for q in queries)
    assert any("UPDATE encounters" in q for q in queries)
    assert any("INSERT INTO audit_log" in q for q in queries)
