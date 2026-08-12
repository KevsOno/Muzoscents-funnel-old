import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json().get("status") == "healthy"

def test_diagnose():
    response = client.get("/api/diagnose")
    assert response.status_code == 200
    data = response.json()
    assert "supabase_ok" in data
