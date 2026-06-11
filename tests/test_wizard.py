"""End-to-end test for the report-creation wizard.

Drives a session through the full six-step wizard via the FastAPI state router
(source_data -> report_name -> vehicles -> channels -> aggregations -> ready),
asserting that each step gates advancement and that the assembled ReportState
generates a valid report.

Only the state router is mounted, and the flow deliberately avoids the discovery
endpoints (channel-catalog, fetch-vehicle-candidates, suggest-bins) that issue
SQL/LLM calls — every step here is driven directly, so no Databricks access is
needed.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.code_generator import generate_all_files
from server.models import ReportState, WizardStep
from server.routes.state import router
from server.routes.state import _sessions  # shared in-memory session store


@pytest.fixture
def client() -> TestClient:
    _sessions.clear()
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    _sessions.clear()


def _start_session(client: TestClient) -> str:
    """Create a session at the SOURCE_DATA step pointing at an existing Silver layer."""
    resp = client.post(
        "/api/set-source-data",
        json={"mode": "existing", "silver_catalog": "cat", "silver_schema": "sch"},
    )
    assert resp.status_code == 200
    return resp.json()["session_id"]


def _step(client: TestClient, sid: str) -> str:
    return client.get(f"/api/state/{sid}").json()["wizard_step"]


class TestWizardStepGating:
    def test_fresh_session_starts_at_source_data(self, client):
        sid = _start_session(client)
        assert _step(client, sid) == WizardStep.SOURCE_DATA.value

    def test_advance_blocks_on_each_incomplete_step(self, client):
        sid = _start_session(client)

        # source_data is complete (existing + catalog/schema) -> advances
        assert client.post(f"/api/advance-step/{sid}").status_code == 200
        assert _step(client, sid) == WizardStep.REPORT_NAME.value

        # report_name empty -> blocked
        r = client.post(f"/api/advance-step/{sid}")
        assert r.status_code == 400
        assert "report name" in r.json()["detail"].lower()

        client.post(f"/api/set-metadata/{sid}", json={"name": "My Report"})
        assert client.post(f"/api/advance-step/{sid}").status_code == 200
        assert _step(client, sid) == WizardStep.VEHICLES.value

        # no vehicles -> blocked
        r = client.post(f"/api/advance-step/{sid}")
        assert r.status_code == 400
        assert "vehicle" in r.json()["detail"].lower()

    def test_advance_unknown_session_is_404(self, client):
        assert client.post("/api/advance-step/nope").status_code == 404


class TestWizardCreatesReport:
    def test_full_walk_through_then_generate_report(self, client):
        sid = _start_session(client)

        # --- Step 1: source data already set; advance to report_name
        assert client.post(f"/api/advance-step/{sid}").status_code == 200

        # --- Step 2: report name
        meta = client.post(f"/api/set-metadata/{sid}", json={"name": "My Report"})
        assert meta.status_code == 200
        assert meta.json()["report_state"]["name"] == "my_report"  # normalized
        assert client.post(f"/api/advance-step/{sid}").status_code == 200
        assert _step(client, sid) == WizardStep.VEHICLES.value

        # --- Step 3: vehicles
        veh = client.post(
            f"/api/select-vehicles/{sid}",
            json={"selected": [{"vehicle_id": "vw_golf", "start_ts": "2024-01-01"}]},
        )
        assert veh.status_code == 200
        assert veh.json()["added"] == ["vw_golf"]
        assert client.post(f"/api/advance-step/{sid}").status_code == 200
        assert _step(client, sid) == WizardStep.CHANNELS.value

        # --- Step 4: channels (add a physical signal)
        sig = client.post(
            f"/api/select-candidates/{sid}",
            json={"selected": [{"alias": "nmot", "var_name": "engine_speed", "channel_name": "nmot"}]},
        )
        assert sig.status_code == 200
        assert sig.json()["added"] == ["engine_speed"]
        assert client.post(f"/api/advance-step/{sid}").status_code == 200
        assert _step(client, sid) == WizardStep.AGGREGATIONS.value

        # --- Step 5: aggregations (add a duration histogram)
        hist = client.post(
            f"/api/add-histogram/{sid}",
            json={
                "name": "rpm_hist",
                "histogram_type": "duration",
                "signal_ref": "engine_speed",
                "bins": [0, 1000, 2000, 7000],
                "bins_unit": "rpm",
            },
        )
        assert hist.status_code == 200
        assert client.post(f"/api/advance-step/{sid}").status_code == 200
        assert _step(client, sid) == WizardStep.READY.value

        # --- Final step: advancing past ready is rejected
        r = client.post(f"/api/advance-step/{sid}")
        assert r.status_code == 400
        assert "final step" in r.json()["detail"].lower()

        # --- The assembled state is a complete, valid report
        state = ReportState.model_validate(client.get(f"/api/state/{sid}").json())
        assert state.name == "my_report"
        assert [v.vehicle_id for v in state.vehicles] == ["vw_golf"]
        assert [s.var_name for s in state.signals] == ["engine_speed"]
        assert [a.name for a in state.aggregations] == ["rpm_hist"]
        # selecting vehicles auto-populated the Silver data sources
        assert state.data_sources.container_metrics == "cat.sch.container_metrics"

        # --- And it generates a runnable report
        files = generate_all_files(state)
        nb = files["src/report.py"]
        assert "engine_speed = query.channel(" in nb
        assert "HistogramDuration(" in nb
        assert 'name="rpm_hist"' in nb

        cfg = json.loads(files["src/config/dev_config.json"])
        assert cfg["unity_sink"]["catalog"] == "cat"
        assert cfg["unity_sink"]["table_prefix"] == "my_report_report"
        assert cfg["units_under_test"][0]["uut_name"]["value"] == "vw_golf"

    def test_add_histogram_rejects_unknown_signal(self, client):
        """A guard worth locking in: aggregations can't reference a signal that
        was never added in the channels step."""
        sid = _start_session(client)
        r = client.post(
            f"/api/add-histogram/{sid}",
            json={
                "name": "h",
                "histogram_type": "duration",
                "signal_ref": "ghost",
                "bins": [0, 1],
            },
        )
        assert r.status_code == 400
        assert "does not exist" in r.json()["detail"]


class TestWizardNavigation:
    def _build_ready_session(self, client: TestClient) -> str:
        sid = _start_session(client)
        client.post(f"/api/advance-step/{sid}")  # -> report_name
        client.post(f"/api/set-metadata/{sid}", json={"name": "r"})
        client.post(f"/api/advance-step/{sid}")  # -> vehicles
        client.post(
            f"/api/select-vehicles/{sid}",
            json={"selected": [{"vehicle_id": "v1", "start_ts": "2024-01-01"}]},
        )
        client.post(f"/api/advance-step/{sid}")  # -> channels
        return sid

    def test_go_back_moves_to_previous_step(self, client):
        sid = self._build_ready_session(client)
        assert _step(client, sid) == WizardStep.CHANNELS.value
        r = client.post(f"/api/go-back/{sid}")
        assert r.status_code == 200
        assert r.json()["wizard_step"] == WizardStep.VEHICLES.value

    def test_go_back_from_first_step_is_rejected(self, client):
        sid = _start_session(client)
        r = client.post(f"/api/go-back/{sid}")
        assert r.status_code == 400

    def test_goto_step_rejects_jump_over_incomplete_prior(self, client):
        sid = self._build_ready_session(client)
        # channels has no signals yet -> cannot jump to aggregations
        r = client.post(f"/api/goto-step/{sid}/aggregations")
        assert r.status_code == 400
        assert "not complete" in r.json()["detail"].lower()

    def test_goto_step_rejects_invalid_step_name(self, client):
        sid = _start_session(client)
        assert client.post(f"/api/goto-step/{sid}/banana").status_code == 400
