"""Tests for SchemaProfile validation and profile loading in server/schema_profile.py."""

from __future__ import annotations

import textwrap

import pytest
from pydantic import ValidationError

import server.schema_profile as sp
from server.schema_profile import SchemaProfile, get_profile, reset_profile_cache


class TestSchemaProfileValidation:
    def test_default_profile_is_valid(self):
        p = SchemaProfile()
        assert p.name == "default"
        assert p.vehicle_source == "tag"
        assert p.container_tags_table == "container_tags"

    def test_tag_source_requires_container_tags_table(self):
        with pytest.raises(ValidationError, match="requires container_tags_table"):
            SchemaProfile(vehicle_source="tag", container_tags_table=None)

    def test_column_source_requires_vehicle_column(self):
        with pytest.raises(ValidationError, match="requires vehicle_column"):
            SchemaProfile(vehicle_source="column")

    def test_column_source_with_column_is_valid(self):
        p = SchemaProfile(vehicle_source="column", vehicle_column="vin")
        assert p.vehicle_column == "vin"

    def test_constant_source_requires_constant(self):
        with pytest.raises(ValidationError, match="requires vehicle_constant"):
            SchemaProfile(vehicle_source="constant")

    def test_constant_source_with_value_is_valid(self):
        p = SchemaProfile(vehicle_source="constant", vehicle_constant="fleet_1")
        assert p.vehicle_constant == "fleet_1"

    def test_rejects_unknown_vehicle_source(self):
        with pytest.raises(ValidationError):
            SchemaProfile(vehicle_source="satellite")

    def test_measurement_dimensions_default_is_independent_per_instance(self):
        a = SchemaProfile()
        a.framework_measurement_dimensions.append("extra")
        b = SchemaProfile()
        assert "extra" not in b.framework_measurement_dimensions


class TestGetProfile:
    def test_returns_default_when_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sp, "_PROFILE_PATH", str(tmp_path / "missing.yaml"))
        reset_profile_cache()
        p = get_profile()
        assert p.name == "default"

    def test_loads_from_yaml(self, monkeypatch, tmp_path):
        path = tmp_path / "profiles.yaml"
        path.write_text(
            textwrap.dedent(
                """
                name: customer_x
                container_table: my_containers
                vehicle_source: column
                vehicle_column: vin
                """
            )
        )
        monkeypatch.setattr(sp, "_PROFILE_PATH", str(path))
        reset_profile_cache()
        p = get_profile()
        assert p.name == "customer_x"
        assert p.container_table == "my_containers"
        assert p.vehicle_source == "column"

    def test_yaml_defaults_end_time_col_to_none(self, monkeypatch, tmp_path):
        """Customer profiles opt out of step rendering unless explicitly set."""
        path = tmp_path / "profiles.yaml"
        path.write_text("name: c\n")
        monkeypatch.setattr(sp, "_PROFILE_PATH", str(path))
        reset_profile_cache()
        assert get_profile().timeseries_end_time_col is None

    def test_yaml_can_set_end_time_col(self, monkeypatch, tmp_path):
        path = tmp_path / "profiles.yaml"
        path.write_text("name: c\ntimeseries_end_time_col: tend\n")
        monkeypatch.setattr(sp, "_PROFILE_PATH", str(path))
        reset_profile_cache()
        assert get_profile().timeseries_end_time_col == "tend"

    def test_caches_result(self, monkeypatch, tmp_path):
        path = tmp_path / "profiles.yaml"
        path.write_text("name: first\n")
        monkeypatch.setattr(sp, "_PROFILE_PATH", str(path))
        reset_profile_cache()
        assert get_profile().name == "first"

        # Mutating the file without resetting the cache returns the cached value.
        path.write_text("name: second\n")
        assert get_profile().name == "first"

        reset_profile_cache()
        assert get_profile().name == "second"

    def test_empty_yaml_file_uses_defaults(self, monkeypatch, tmp_path):
        path = tmp_path / "profiles.yaml"
        path.write_text("")
        monkeypatch.setattr(sp, "_PROFILE_PATH", str(path))
        reset_profile_cache()
        assert get_profile().name == "default"
