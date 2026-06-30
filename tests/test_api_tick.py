from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import api


def test_tick_rejects_missing_secret_header():
    with patch.object(api.cfg, "MONITOR_TICK_SECRET", "s3cret"), \
         patch("api.list_active_goals_for_monitor", new_callable=AsyncMock, return_value=[]):
        client = TestClient(api.app)
        resp = client.post("/internal/tick")
    assert resp.status_code == 403


def test_tick_rejects_wrong_secret_header():
    with patch.object(api.cfg, "MONITOR_TICK_SECRET", "s3cret"), \
         patch("api.list_active_goals_for_monitor", new_callable=AsyncMock, return_value=[]):
        client = TestClient(api.app)
        resp = client.post("/internal/tick", headers={"X-Tick-Secret": "wrong"})
    assert resp.status_code == 403


def test_tick_accepts_correct_secret_header():
    with patch.object(api.cfg, "MONITOR_TICK_SECRET", "s3cret"), \
         patch("api.list_active_goals_for_monitor", new_callable=AsyncMock, return_value=[]):
        client = TestClient(api.app)
        resp = client.post("/internal/tick", headers={"X-Tick-Secret": "s3cret"})
    assert resp.status_code == 200
    assert resp.json() == {"checked": 0}


def test_tick_open_when_secret_unset():
    # Empty secret disables the header check (local/dev parity).
    with patch.object(api.cfg, "MONITOR_TICK_SECRET", ""), \
         patch("api.list_active_goals_for_monitor", new_callable=AsyncMock, return_value=[]):
        client = TestClient(api.app)
        resp = client.post("/internal/tick")
    assert resp.status_code == 200
