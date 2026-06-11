"""Tests for skill loading and system-prompt assembly in server/skill_loader.py."""

from __future__ import annotations

import textwrap

import pytest

from server.skill_loader import (
    SKILL_NAMES,
    _parse_frontmatter,
    build_system_prompt,
    load_skill_full,
    load_skill_index,
)


class TestParseFrontmatter:
    def test_extracts_flat_keys(self):
        text = textwrap.dedent(
            """\
            ---
            name: my-skill
            description: Does a thing
            ---
            # Body
            """
        )
        fm = _parse_frontmatter(text)
        assert fm == {"name": "my-skill", "description": "Does a thing"}

    def test_strips_quotes(self):
        text = '---\nname: "quoted"\ndesc: \'single\'\n---\nbody'
        fm = _parse_frontmatter(text)
        assert fm["name"] == "quoted"
        assert fm["desc"] == "single"

    def test_ignores_indented_lines(self):
        text = "---\nname: top\n  nested: ignored\n---\n"
        fm = _parse_frontmatter(text)
        assert "name" in fm
        assert "nested" not in fm

    def test_no_frontmatter_returns_empty(self):
        assert _parse_frontmatter("# Just a heading\nno frontmatter") == {}

    def test_frontmatter_must_be_at_start(self):
        text = "preamble\n---\nname: x\n---\n"
        assert _parse_frontmatter(text) == {}


class TestLoadSkillIndex:
    def test_returns_one_entry_per_known_skill(self):
        index = load_skill_index()
        assert {s.name for s in index} == set(SKILL_NAMES)

    def test_every_entry_has_description(self):
        for s in load_skill_index():
            assert s.description


class TestLoadSkillFull:
    def test_unknown_skill_reports_available(self):
        out = load_skill_full("does-not-exist")
        assert "Unknown skill" in out
        assert "create-report" in out

    @pytest.mark.parametrize("name", SKILL_NAMES)
    def test_known_skill_loads_content(self, name):
        out = load_skill_full(name)
        assert f"## Skill: {name}" in out


class TestBuildSystemPrompt:
    def test_includes_skill_catalogue(self):
        prompt = build_system_prompt()
        for name in SKILL_NAMES:
            assert name in prompt

    def test_current_step_rendered(self):
        prompt = build_system_prompt(wizard_step="aggregations")
        assert "AGGREGATIONS" in prompt

    def test_signal_context_listed(self):
        prompt = build_system_prompt(
            wizard_step="channels",
            signals=[
                {"var_name": "rpm", "signal_type": "physical", "channel_name": "nmot"},
                {"var_name": "speed2", "signal_type": "virtual", "expression": "rpm * 2"},
            ],
        )
        assert "Currently Defined Signals" in prompt
        assert "`rpm`" in prompt
        assert "virtual" in prompt

    def test_available_channels_table(self):
        prompt = build_system_prompt(
            available_channels=[
                {"channel_name": "nmot", "unit": "rpm", "sample_count": 100,
                 "min_value": 0.0, "max_value": 7000.0, "mean_value": 2500.0},
            ]
        )
        assert "Available Channels in Silver Layer" in prompt
        assert "nmot" in prompt
        assert "7000.00" in prompt

    def test_available_channels_handles_missing_numeric_fields(self):
        prompt = build_system_prompt(
            available_channels=[{"channel_name": "x", "unit": "", "sample_count": 0}]
        )
        # min/max/mean None must not raise and render as empty cells
        assert "| x |" in prompt

    def test_vehicle_context_sections(self):
        prompt = build_system_prompt(
            vehicle_candidates=[{"vehicle_id": "vw_golf", "datapoint_count": 5}],
            vehicles=[{"vehicle_id": "vw_golf", "col_name": "test_object_name",
                       "start_ts": "2024-01-01", "stop_ts": "2024-02-01"}],
            data_sources={"container_metrics": "cat.sch.cm", "aliases": "cat.sch.al"},
        )
        assert "Vehicle Context" in prompt
        assert "vw_golf" in prompt
        assert "cat.sch.cm" in prompt
        assert "search_aliases" in prompt

    def test_no_optional_context_when_args_empty(self):
        prompt = build_system_prompt()
        assert "Currently Defined Signals" not in prompt
        assert "Available Channels in Silver Layer" not in prompt
        assert "Vehicle Context" not in prompt
