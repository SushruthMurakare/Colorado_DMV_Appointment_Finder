"""
API endpoint tests using FastAPI TestClient.
No real DMV, Supabase, or Resend calls — validation errors are caught before
any external service is touched.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from api import app

client = TestClient(app, raise_server_exceptions=True)

VALID_BODY = {
    "name": "Jane Smith",
    "email": "jane@example.com",
    "office_id": 10,        # Aurora
    "office_name": "Aurora",
    "appt_type": "Written Test",
}


# ── /api/health ───────────────────────────────────────────────────────────────

def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── /api/types ────────────────────────────────────────────────────────────────

def test_types_returns_all_four():
    r = client.get("/api/types")
    assert r.status_code == 200
    types = r.json()["types"]
    assert "Written Test" in types
    assert "CDL Written Test" in types
    assert "First Time CO DL/ID/Permit" in types
    assert "Renew Colorado Driver License/ID/Permit" in types
    assert len(types) == 4


# ── /api/offices ──────────────────────────────────────────────────────────────

def test_offices_returns_list():
    r = client.get("/api/offices")
    assert r.status_code == 200
    offices = r.json()["offices"]
    assert len(offices) > 0
    # Each entry must have id, name, address
    for o in offices:
        assert "id" in o
        assert "name" in o
        assert "address" in o


def test_offices_contains_aurora():
    r = client.get("/api/offices")
    names = [o["name"] for o in r.json()["offices"]]
    assert "Aurora" in names


# ── /api/subscribe — input validation (all 400s hit before Supabase) ──────────

def test_subscribe_missing_name():
    body = {**VALID_BODY, "name": ""}
    r = client.post("/api/subscribe", json=body)
    assert r.status_code == 400
    assert "name" in r.json()["detail"].lower()


def test_subscribe_invalid_email():
    body = {**VALID_BODY, "email": "not-an-email"}
    r = client.post("/api/subscribe", json=body)
    assert r.status_code == 400
    assert "email" in r.json()["detail"].lower()


def test_subscribe_invalid_appt_type():
    body = {**VALID_BODY, "appt_type": "Haircut"}
    r = client.post("/api/subscribe", json=body)
    assert r.status_code == 400
    assert "type" in r.json()["detail"].lower()


def test_subscribe_unknown_office():
    body = {**VALID_BODY, "office_id": 9999}
    r = client.post("/api/subscribe", json=body)
    assert r.status_code == 400
    assert "office" in r.json()["detail"].lower()


def test_subscribe_no_supabase_configured(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    r = client.post("/api/subscribe", json=VALID_BODY)
    assert r.status_code == 503


def test_subscribe_success(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-key")
    fake_sub = {"id": "abc-123"}
    with patch("api.create_subscription", new=AsyncMock(return_value=fake_sub)):
        r = client.post("/api/subscribe", json=VALID_BODY)
    assert r.status_code == 201
    assert r.json()["ok"] is True
    assert r.json()["id"] == "abc-123"


def test_subscribe_with_date_window(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-key")
    body = {**VALID_BODY, "after_date": "2026-07-01", "before_date": "2026-07-31"}
    fake_sub = {"id": "def-456"}
    with patch("api.create_subscription", new=AsyncMock(return_value=fake_sub)) as mock:
        r = client.post("/api/subscribe", json=body)
    assert r.status_code == 201
    call_kwargs = mock.call_args.kwargs
    assert call_kwargs["after_date"] == "2026-07-01"
    assert call_kwargs["before_date"] == "2026-07-31"


# ── /api/unsubscribe ──────────────────────────────────────────────────────────

def test_unsubscribe_no_supabase(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    r = client.get("/api/unsubscribe", params={"token": "sometoken"})
    assert r.status_code == 503


def test_unsubscribe_invalid_token(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-key")
    with patch("api.deactivate_subscription", new=AsyncMock(return_value=False)):
        r = client.get("/api/unsubscribe", params={"token": "bad-token"})
    assert r.status_code == 404


def test_unsubscribe_valid_token(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-key")
    with patch("api.deactivate_subscription", new=AsyncMock(return_value=True)):
        r = client.get("/api/unsubscribe", params={"token": "valid-token"})
    assert r.status_code == 200
    assert "Unsubscribed" in r.text
