"""Tests for the LLM agent's tool layer in server/agent.py.

Covers the deterministic parts — session handling, every tool implementation
(_exec_*), the step-gated dispatcher, the markdown/auto-suggest fallback — plus
the run_agent tool-calling loop driven by a fake OpenAI client. No network or
real LLM is involved.
"""

from __future__ import annotations

import pytest

import server.agent as agent
from server.agent import (
    _dispatch_tool,
    _exec_add_event,
    _exec_add_histogram,
    _exec_add_histogram_2d,
    _exec_add_physical_signal,
    _exec_add_statistics,
    _exec_add_virtual_signal,
    _exec_preview_code,
    _exec_remove_aggregation,
    _exec_search_aliases,
    _exec_set_data_sources,
    _exec_set_report_metadata,
    _exec_set_vehicle,
    _exec_suggest_candidates,
    _extract_aliases_from_markdown,
    _get_session,
    _maybe_auto_suggest_candidates,
    run_agent,
)
from server.models import (
    Histogram1DDefinition,
    ReportState,
    StatisticsDefinition,
    WizardStep,
)


@pytest.fixture(autouse=True)
def _clear_sessions():
    agent._sessions.clear()
    # Reset the MCP discovery cache so monkeypatched tools don't leak across tests.
    agent._mcp_tools_cache = None
    yield
    agent._sessions.clear()
    agent._mcp_tools_cache = None


@pytest.fixture
def state() -> ReportState:
    return ReportState()


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------

class TestGetSession:
    def test_creates_new_session_when_id_unknown(self):
        s = _get_session(None)
        assert s.session_id in agent._sessions
        assert isinstance(s.state, ReportState)

    def test_reuses_existing_session(self):
        s1 = _get_session("abc")
        s1.state.name = "kept"
        s2 = _get_session("abc")
        assert s2 is s1
        assert s2.state.name == "kept"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

class TestExecPhysicalSignal:
    def test_adds_signal_with_channel_name_fallback_to_alias(self, state):
        msg = _exec_add_physical_signal(state, "rpm", "nmot")
        assert "Added physical signal 'rpm'" in msg
        assert state.signals[0].channel_name == "nmot"  # fell back to alias

    def test_rejects_duplicate(self, state):
        _exec_add_physical_signal(state, "rpm", "nmot")
        msg = _exec_add_physical_signal(state, "rpm", "nmot")
        assert "already exists" in msg
        assert len(state.signals) == 1

    def test_signal_network_qualifier_in_message(self, state):
        msg = _exec_add_physical_signal(state, "rpm", "nmot", signal="EngSpd", network="CAN1")
        assert "signal='EngSpd', network='CAN1'" in msg


class TestExecVirtualSignal:
    def test_adds_virtual_signal(self, state):
        msg = _exec_add_virtual_signal(state, "x2", "rpm * 2", "SampleSeries")
        assert "Added virtual signal 'x2'" in msg
        assert state.signals[0].signal_type == "virtual"

    def test_rejects_duplicate(self, state):
        _exec_add_virtual_signal(state, "x2", "rpm * 2", "SampleSeries")
        msg = _exec_add_virtual_signal(state, "x2", "rpm * 3", "SampleSeries")
        assert "already exists" in msg


class TestExecSuggestCandidates:
    def test_deduplicates_by_alias_and_defaults_channel_name(self, state):
        msg = _exec_suggest_candidates(
            state, [{"alias": "a"}, {"alias": "a"}, {"alias": "b", "unit": "rpm"}]
        )
        assert "Presented 2 unique candidate(s)" in msg
        assert [c.alias for c in state.signal_candidates] == ["a", "b"]
        assert state.signal_candidates[0].channel_name == "a"  # defaulted to alias


class TestExecAggregations:
    def test_add_event_and_output_type(self, state):
        msg = _exec_add_event(
            state, name="hot", event_type="interval",
            conditions=[{"signal_ref": "rpm", "operator": ">", "value": 1}],
        )
        assert "output: Intervals" in msg
        assert state.events[0].name == "hot"

    def test_add_histogram(self, state):
        msg = _exec_add_histogram(
            state, name="h", histogram_type="duration", signal_ref="rpm", bins=[0, 1, 2]
        )
        assert "Added duration histogram 'h'" in msg
        assert isinstance(state.aggregations[0], Histogram1DDefinition)

    def test_add_histogram_rejects_duplicate(self, state):
        _exec_add_histogram(state, name="h", histogram_type="duration", signal_ref="rpm", bins=[0, 1])
        msg = _exec_add_histogram(state, name="h", histogram_type="duration", signal_ref="rpm", bins=[0, 1])
        assert "already exists" in msg
        assert len(state.aggregations) == 1

    def test_add_histogram_2d(self, state):
        msg = _exec_add_histogram_2d(
            state, name="map", x_signal_ref="rpm", y_signal_ref="trq",
            x_bins=[0, 1], y_bins=[0, 1, 2],
        )
        assert "Added 2D histogram 'map'" in msg
        assert state.aggregations[0].agg_kind == "histogram_2d"

    def test_add_histogram_2d_rejects_duplicate(self, state):
        _exec_add_histogram_2d(state, name="map", x_signal_ref="a", y_signal_ref="b", x_bins=[0, 1], y_bins=[0, 1])
        msg = _exec_add_histogram_2d(state, name="map", x_signal_ref="a", y_signal_ref="b", x_bins=[0, 1], y_bins=[0, 1])
        assert "already exists" in msg
        assert len(state.aggregations) == 1

    def test_add_statistics_defaults_stat_labels(self, state):
        _exec_add_statistics(state, name="s", signal_refs=["rpm"])
        agg = state.aggregations[0]
        assert isinstance(agg, StatisticsDefinition)
        assert agg.stat_labels == ["min", "max", "mean", "median"]

    def test_remove_aggregation(self, state):
        _exec_add_histogram(state, name="h", histogram_type="duration", signal_ref="rpm", bins=[0, 1])
        assert "Removed" in _exec_remove_aggregation(state, "h")
        assert state.aggregations == []

    def test_remove_missing_aggregation(self, state):
        assert "not found" in _exec_remove_aggregation(state, "ghost")


class TestExecMetadataVehiclesDataSources:
    def test_set_report_metadata_normalizes_name(self, state):
        msg = _exec_set_report_metadata(state, "My Cool Report")
        assert state.name == "my_cool_report"
        assert state.description == "my_cool_report Report"
        assert state.data_sources.table_prefix == "my_cool_report_report"
        assert "my_cool_report" in msg

    def test_set_vehicle_add_then_update(self, state):
        _exec_set_vehicle(state, "v1", "2024-01-01")
        assert state.vehicles[0].col_name == state.vehicle_col_name
        msg = _exec_set_vehicle(state, "v1", "2024-02-01", col_name="vin", stop_ts="2024-03-01")
        assert "Updated vehicle 'v1'" in msg
        assert len(state.vehicles) == 1
        assert state.vehicles[0].start_ts == "2024-02-01"
        assert state.vehicles[0].col_name == "vin"

    def test_set_vehicle_clears_candidates_on_add(self, state):
        from server.models import VehicleCandidate

        state.vehicle_candidates = [VehicleCandidate(vehicle_id="v1"), VehicleCandidate(vehicle_id="v2")]
        _exec_set_vehicle(state, "v1", "2024-01-01")
        # Mirrors the UI select-vehicles route so the "Available Vehicles" picker hides.
        assert state.vehicle_candidates == []

    def test_set_vehicle_auto_populates_silver_data_sources(self, state):
        """Like the UI route, adding a vehicle must resolve the silver data sources
        so later agent turns keep the container_metrics table in their context."""
        from server.models import SourceDataMode

        state.source_data.mode = SourceDataMode.EXISTING
        state.source_data.silver_catalog = "cat"
        state.source_data.silver_schema = "sch"
        _exec_set_vehicle(state, "v1", "2024-01-01")
        assert state.data_sources.container_metrics.startswith("cat.sch.")
        assert state.data_sources.channel_metrics.startswith("cat.sch.")
        assert state.data_sources.channels  # non-empty

    def test_set_data_sources_applies_defaults(self, state):
        state.name = "rep"
        _exec_set_data_sources(
            state, container_metrics="c.s.cm", channel_metrics="c.s.chm", channels=["c.s.ch"]
        )
        ds = state.data_sources
        assert ds.aliases_copy_table_name == "channel_aliases"
        assert ds.device_aliases_copy_table_name == "device_aliases"
        assert ds.table_prefix == "rep_report"


class TestExecSearchAliases:
    def test_returns_message_when_silver_layer_unconfigured(self, state):
        msg = _exec_search_aliases(state, "temp")
        assert "not configured" in msg

    def test_returns_message_when_profile_has_no_aliases_table(self, state):
        # Default SchemaProfile has aliases_table=None, so the query builder returns
        # None and the tool tells the agent to fall back to the channel catalog.
        state.source_data.silver_catalog = "cat"
        state.source_data.silver_schema = "sch"
        msg = _exec_search_aliases(state, "temp")
        assert "no aliases table" in msg.lower()

    def test_success_path_formats_rows(self, state, monkeypatch):
        from server.schema_profile import SchemaProfile
        import server.schema_adapter as sa
        monkeypatch.setattr(sa, "get_profile", lambda: SchemaProfile(aliases_table="al"))
        import server.mcp_tools as mcp
        monkeypatch.setattr(
            mcp, "execute_sql",
            lambda sql, user_token=None: {
                "columns": ["channel_alias_name", "channel_name", "signal", "network", "unit", "description"],
                "rows": [["nmot", "nmot", "EngSpd", "CAN1", "rpm", "engine speed"]],
            },
        )
        state.source_data.silver_catalog = "cat"
        state.source_data.silver_schema = "sch"
        msg = _exec_search_aliases(state, "speed")
        assert "Found 1 match" in msg
        assert "nmot" in msg


class TestExecPreviewCode:
    def test_preview_includes_both_artifacts(self, state):
        _exec_set_report_metadata(state, "rep")
        _exec_add_physical_signal(state, "rpm", "nmot")
        _exec_add_histogram(state, name="h", histogram_type="duration", signal_ref="rpm", bins=[0, 1])
        out = _exec_preview_code(state)
        assert "report.py" in out
        assert "dev_config.json" in out
        assert "rpm = query.channel(" in out


# ---------------------------------------------------------------------------
# Dispatcher (step gating + routing)
# ---------------------------------------------------------------------------

class TestDispatchTool:
    def test_blocks_tool_outside_its_step(self, state):
        # set_report_metadata is only allowed during REPORT_NAME; on VEHICLES it's blocked.
        state.wizard_step = WizardStep.VEHICLES
        msg = _dispatch_tool(state, "set_report_metadata", {"name": "x"}, {})
        assert "cannot be used during" in msg
        assert "Report Name" in msg  # tells the user where it IS available
        assert state.name == ""  # not applied

    def test_blocks_gated_tool_on_source_data_step(self, state):
        """Regression: SOURCE_DATA must have a label so blocking a step-gated tool
        while on the source-data step returns the friendly message instead of
        raising KeyError (which would crash run_agent mid-turn)."""
        state.wizard_step = WizardStep.SOURCE_DATA
        msg = _dispatch_tool(state, "set_report_metadata", {"name": "x"}, {})
        assert "cannot be used during" in msg
        assert "Source Data" in msg
        assert state.name == ""  # not applied

    def test_routes_to_exec_when_step_allows(self, state):
        state.wizard_step = WizardStep.REPORT_NAME
        _dispatch_tool(state, "set_report_metadata", {"name": "My Report"}, {})
        assert state.name == "my_report"

    def test_unknown_tool(self, state):
        state.wizard_step = WizardStep.CHANNELS
        assert "Unknown tool" in _dispatch_tool(state, "nope", {}, {})

    def test_routes_signal_and_aggregation_tools(self, state):
        state.wizard_step = WizardStep.CHANNELS
        _dispatch_tool(state, "add_physical_signal", {"var_name": "rpm", "alias": "nmot"}, {})
        assert state.signals[0].var_name == "rpm"

        state.wizard_step = WizardStep.AGGREGATIONS
        _dispatch_tool(
            state, "add_histogram",
            {"name": "h", "histogram_type": "duration", "signal_ref": "rpm", "bins": [0, 1]}, {},
        )
        assert state.aggregations[0].name == "h"

    def test_routes_to_mcp_tool(self, state, monkeypatch):
        called = {}
        def fake_call(name, args, user_token=None):
            called["name"] = name
            called["args"] = args
            return "MCP_OK"
        monkeypatch.setattr(agent, "call_mcp_tool", fake_call)
        # MCP tools aren't in the step map, so they're allowed at any step.
        out = _dispatch_tool(state, "mcp_foo", {"q": 1}, {"mcp_foo": "foo"})
        assert out == "MCP_OK"
        assert called == {"name": "foo", "args": {"q": 1}}


# ---------------------------------------------------------------------------
# advance_step (agent-side "Next Step")
# ---------------------------------------------------------------------------

class TestToolGating:
    def test_set_data_sources_hidden_in_silver_mode(self, monkeypatch):
        """No mapping table -> set_data_sources must not be offered to the model
        (it would clobber the auto-resolved silver tables)."""
        monkeypatch.delenv("IMPULSE_MAPPING_TABLE", raising=False)
        agent._mcp_tools_cache = ([], {})
        tools, _ = agent._get_all_tools()
        names = [t["function"]["name"] for t in tools]
        assert "set_data_sources" not in names

    def test_set_data_sources_offered_with_mapping_table(self, monkeypatch):
        monkeypatch.setenv("IMPULSE_MAPPING_TABLE", "cat.sch.mapping")
        agent._mcp_tools_cache = ([], {})
        tools, _ = agent._get_all_tools()
        names = [t["function"]["name"] for t in tools]
        assert "set_data_sources" in names


class TestAdvanceStep:
    def test_registered_as_tool(self):
        names = [t["function"]["name"] for t in agent.TOOLS]
        assert "advance_step" in names

    def test_advances_when_current_step_complete(self, state):
        state.wizard_step = WizardStep.REPORT_NAME
        state.name = "demo"
        msg = _dispatch_tool(state, "advance_step", {}, {})
        assert state.wizard_step == WizardStep.VEHICLES
        assert "Vehicles" in msg

    def test_blocks_when_current_step_incomplete(self, state):
        state.wizard_step = WizardStep.REPORT_NAME
        state.name = ""  # nothing set
        msg = _dispatch_tool(state, "advance_step", {}, {})
        assert state.wizard_step == WizardStep.REPORT_NAME  # unchanged
        assert "report name" in msg.lower()

    def test_allowed_in_any_step_unlike_gated_tools(self, state):
        # Not in _TOOL_STEP_MAP, so it isn't blocked by the step gate.
        assert "advance_step" not in agent._TOOL_STEP_MAP

    def test_noop_on_final_step(self, state):
        state.wizard_step = WizardStep.READY
        msg = _dispatch_tool(state, "advance_step", {}, {})
        assert state.wizard_step == WizardStep.READY
        assert "final step" in msg.lower()

    def test_load_skill_returns_content(self, state):
        state.wizard_step = WizardStep.CHANNELS
        out = _dispatch_tool(state, "load_skill", {"skill_name": "define-channels"}, {})
        assert "Skill: define-channels" in out


# ---------------------------------------------------------------------------
# Markdown alias extraction + auto-suggest fallback
# ---------------------------------------------------------------------------

class TestExtractAliases:
    def test_parses_single_column_table_skipping_header_and_rule(self):
        md = "| channelAlias |\n| --- |\n| nmot |\n| tKueMi |\n"
        assert _extract_aliases_from_markdown(md) == ["nmot", "tKueMi"]

    def test_empty_when_no_table(self):
        assert _extract_aliases_from_markdown("no table here") == []


class TestMaybeAutoSuggest:
    def _md(self):
        return "| channelAlias |\n| --- |\n| nmot |\n"

    def test_populates_candidates_when_sql_ran_without_suggest(self, state):
        state.wizard_step = WizardStep.CHANNELS
        _maybe_auto_suggest_candidates(
            state, called_sql=True, called_suggest=False, last_sql_result=self._md()
        )
        assert [c.alias for c in state.signal_candidates] == ["nmot"]

    def test_noop_when_available_channels_present(self, state):
        from server.models import AvailableChannel
        state.wizard_step = WizardStep.CHANNELS
        state.available_channels = [AvailableChannel(channel_name="x")]
        _maybe_auto_suggest_candidates(
            state, called_sql=True, called_suggest=False, last_sql_result=self._md()
        )
        assert state.signal_candidates == []

    def test_noop_when_not_on_channels_step(self, state):
        state.wizard_step = WizardStep.AGGREGATIONS
        _maybe_auto_suggest_candidates(
            state, called_sql=True, called_suggest=False, last_sql_result=self._md()
        )
        assert state.signal_candidates == []

    def test_noop_when_suggest_already_called(self, state):
        state.wizard_step = WizardStep.CHANNELS
        _maybe_auto_suggest_candidates(
            state, called_sql=True, called_suggest=True, last_sql_result=self._md()
        )
        assert state.signal_candidates == []


# ---------------------------------------------------------------------------
# run_agent loop with a fake OpenAI client
# ---------------------------------------------------------------------------

class _FakeFn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = _FakeFn(name, arguments)


class _FakeMsg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=False):
        return {"role": "assistant", "content": self.content}


class _FakeChoice:
    def __init__(self, msg):
        self.message = msg


class _FakeResp:
    def __init__(self, msg):
        self.choices = [_FakeChoice(msg)]


class _FakeCompletions:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResp(self._scripted.pop(0))


class _FakeClient:
    def __init__(self, scripted):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(scripted)})()


@pytest.fixture
def patch_agent_llm(monkeypatch):
    """Patch out the network-bound bits of run_agent, returning a setter for the
    scripted LLM responses."""
    monkeypatch.setattr(agent, "build_system_prompt", lambda **k: "system")
    monkeypatch.setattr(agent, "resolve_serving_endpoint", lambda *a, **k: "ep")
    monkeypatch.setattr(agent, "_get_all_tools", lambda user_token=None: (agent.TOOLS, {}))

    def _set(scripted):
        client = _FakeClient(scripted)
        monkeypatch.setattr(agent, "_get_openai_client", lambda user_token=None: client)
        return client

    return _set


class TestRunAgent:
    def test_plain_text_response_no_tools(self, patch_agent_llm):
        patch_agent_llm([_FakeMsg(content="Hello there")])
        text, state, sid = run_agent("hi", session_id="sess")
        assert text == "Hello there"
        assert sid == "sess"
        # conversation persisted on the session
        assert agent._sessions["sess"].messages[-1] == {"role": "assistant", "content": "Hello there"}

    def test_tool_call_then_final_text(self, patch_agent_llm):
        # Pre-seed the session at the REPORT_NAME step so set_report_metadata is allowed.
        sess = _get_session("sess")
        sess.state.wizard_step = WizardStep.REPORT_NAME

        client = patch_agent_llm([
            _FakeMsg(tool_calls=[_FakeToolCall("c1", "set_report_metadata", '{"name": "My Report"}')]),
            _FakeMsg(content="Report name set."),
        ])

        text, state, sid = run_agent("call the tool", session_id="sess")
        assert text == "Report name set."
        assert state.name == "my_report"  # the tool actually ran
        # two LLM rounds: the tool call, then the final text
        assert len(client.chat.completions.calls) == 2

    def test_advance_step_ends_turn_without_acting_on_new_step(self, patch_agent_llm):
        """After advance_step the turn must end, so the model can't keep acting on
        the just-unlocked step with stale context (the wrong-tables bug)."""
        sess = _get_session("sess")
        sess.state.wizard_step = WizardStep.REPORT_NAME
        sess.state.name = "demo"  # current step is complete -> advance succeeds

        client = patch_agent_llm([
            _FakeMsg(tool_calls=[_FakeToolCall("c1", "advance_step", "{}")]),
            # Would corrupt data sources if the loop kept going — must NOT run.
            _FakeMsg(tool_calls=[_FakeToolCall("c2", "set_data_sources",
                '{"container_metrics": "wrong.t.c", "channel_metrics": "wrong.t.cm", "channels": ["wrong.t.ch"]}')]),
        ])

        text, state, _sid = run_agent("go ahead", session_id="sess")
        assert state.wizard_step == WizardStep.VEHICLES
        assert "Vehicles" in text
        # The turn ended after one LLM round — the second (table-guessing) call never ran.
        assert len(client.chat.completions.calls) == 1
        assert state.data_sources.container_metrics == ""

    def test_stops_after_max_tool_rounds(self, patch_agent_llm):
        """If the model keeps calling tools forever, the loop bails out after
        _MAX_TOOL_ROUNDS rather than looping indefinitely."""
        sess = _get_session("sess")
        sess.state.wizard_step = WizardStep.READY  # load_skill is allowed here

        # Always return a tool call, never a terminating text message.
        scripted = [
            _FakeMsg(tool_calls=[_FakeToolCall(f"c{i}", "load_skill", '{"skill_name": "define-channels"}')])
            for i in range(agent._MAX_TOOL_ROUNDS)
        ]
        client = patch_agent_llm(scripted)

        text, _state, _sid = run_agent("loop forever", session_id="sess")
        assert len(client.chat.completions.calls) == agent._MAX_TOOL_ROUNDS
        # falls back to the last tool result rather than crashing
        assert "Skill: define-channels" in text
