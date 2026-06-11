"""Tests for Pydantic models and their validators in server/models.py."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from server.models import (
    AggregationDefinition,
    EvalType,
    EventDefinition,
    Histogram1DDefinition,
    Histogram2DDefinition,
    HistogramType,
    ReportState,
    SignalDefinition,
    StatisticsDefinition,
    ThresholdCondition,
    WIZARD_ORDER,
    WizardStep,
)


class TestSignalDefinition:
    def test_minimal_physical_signal_defaults(self):
        sig = SignalDefinition(var_name="nmot")
        assert sig.signal_type == "physical"
        assert sig.eval_type == EvalType.SAMPLE_SERIES
        assert sig.expression is None

    def test_rejects_invalid_signal_type(self):
        with pytest.raises(ValidationError):
            SignalDefinition(var_name="x", signal_type="imaginary")


class TestEventDefinition:
    def test_interval_requires_condition(self):
        with pytest.raises(ValidationError, match="requires at least one condition"):
            EventDefinition(name="e", event_type="interval", conditions=[])

    def test_rising_edges_empty_conditions_rejected(self):
        with pytest.raises(ValidationError, match="requires at least one condition"):
            EventDefinition(name="e", event_type="rising_edges", conditions=[])

    def test_omitting_conditions_bypasses_the_check(self):
        """Known gap: the conditions validator only runs when the field is
        explicitly supplied, so omitting it entirely is silently accepted even
        for event types that require a condition."""
        evt = EventDefinition(name="e", event_type="rising_edges")
        assert evt.conditions == []

    def test_change_points_does_not_require_condition(self):
        evt = EventDefinition(
            name="gear_shift",
            event_type="change_points",
            signal_ref="gear",
            from_state=1,
            to_state=2,
        )
        assert evt.conditions == []

    def test_periodic_distance_requires_positive_step(self):
        with pytest.raises(ValidationError, match="positive 'step'"):
            EventDefinition(
                name="km",
                event_type="periodic_distance",
                signal_ref="odo",
                step=0,
            )

    def test_periodic_distance_requires_signal_ref(self):
        with pytest.raises(ValidationError, match="require 'signal_ref'"):
            EventDefinition(
                name="km",
                event_type="periodic_distance",
                step=1000,
            )

    def test_periodic_distance_valid(self):
        evt = EventDefinition(
            name="km",
            event_type="periodic_distance",
            signal_ref="odo",
            step=1000,
        )
        assert evt.output_type == "Intervals"

    @pytest.mark.parametrize(
        "event_type,expected",
        [
            ("interval", "Intervals"),
            ("periodic_distance", "Intervals"),
            ("rising_edges", "PointsInTime"),
            ("falling_edges", "PointsInTime"),
            ("change_points", "PointsInTime"),
        ],
    )
    def test_output_type(self, event_type, expected):
        kwargs: dict = {"name": "e", "event_type": event_type}
        if event_type in ("interval", "rising_edges", "falling_edges"):
            kwargs["conditions"] = [ThresholdCondition(signal_ref="s", operator=">", value=1)]
        if event_type == "periodic_distance":
            kwargs.update(signal_ref="odo", step=10)
        if event_type == "change_points":
            kwargs.update(signal_ref="gear", from_state=1, to_state=2)
        assert EventDefinition(**kwargs).output_type == expected


class TestThresholdCondition:
    def test_rejects_unknown_operator(self):
        with pytest.raises(ValidationError):
            ThresholdCondition(signal_ref="s", operator="=>", value=1)

    @pytest.mark.parametrize("op", [">", "<", ">=", "<=", "==", "!="])
    def test_accepts_known_operators(self, op):
        cond = ThresholdCondition(signal_ref="s", operator=op, value=1.5)
        assert cond.operator == op


class TestHistogram1DDefinition:
    def test_duration_histogram_no_weight_required(self):
        h = Histogram1DDefinition(
            name="h", histogram_type=HistogramType.DURATION, signal_ref="s", bins=[0, 1]
        )
        assert h.weight_signal_ref is None
        assert h.agg_kind == "histogram_1d"

    def test_distance_histogram_explicit_none_weight_rejected(self):
        with pytest.raises(ValidationError, match="require weight_signal_ref"):
            Histogram1DDefinition(
                name="h",
                histogram_type=HistogramType.DISTANCE,
                signal_ref="s",
                bins=[0, 1],
                weight_signal_ref=None,
            )

    def test_distance_histogram_omitting_weight_bypasses_check(self):
        """Known gap: the weight validator only fires when weight_signal_ref is
        explicitly provided. Omitting it constructs successfully — the missing
        weight is instead caught later in code_generator.generate_report_notebook."""
        h = Histogram1DDefinition(
            name="h",
            histogram_type=HistogramType.DISTANCE,
            signal_ref="s",
            bins=[0, 1],
        )
        assert h.weight_signal_ref is None

    def test_distance_histogram_with_weight(self):
        h = Histogram1DDefinition(
            name="h",
            histogram_type=HistogramType.DISTANCE,
            signal_ref="s",
            bins=[0, 1],
            weight_signal_ref="odo",
        )
        assert h.weight_signal_ref == "odo"


class TestAggregationUnion:
    """The discriminated union must route dicts to the right subtype via agg_kind."""

    adapter = TypeAdapter(AggregationDefinition)

    def test_dict_without_kind_defaults_to_histogram_1d(self):
        agg = self.adapter.validate_python(
            {"name": "h", "signal_ref": "s", "bins": [0, 1]}
        )
        assert isinstance(agg, Histogram1DDefinition)

    def test_routes_to_histogram_2d(self):
        agg = self.adapter.validate_python(
            {
                "agg_kind": "histogram_2d",
                "name": "h2",
                "x_signal_ref": "x",
                "y_signal_ref": "y",
            }
        )
        assert isinstance(agg, Histogram2DDefinition)

    def test_routes_to_statistics(self):
        agg = self.adapter.validate_python(
            {"agg_kind": "statistics", "name": "stats", "signal_refs": ["a", "b"]}
        )
        assert isinstance(agg, StatisticsDefinition)
        assert agg.stat_labels == ["min", "max", "mean", "median"]


class TestReportState:
    def test_defaults(self):
        rs = ReportState()
        assert rs.wizard_step == WizardStep.SOURCE_DATA
        assert rs.signals == []
        assert rs.aggregations == []
        assert rs.deployment.value == "not_started"

    def test_aggregations_parsed_into_union_types(self):
        rs = ReportState(
            name="r",
            aggregations=[
                {"agg_kind": "statistics", "name": "s", "signal_refs": ["a"]},
                {"name": "h", "signal_ref": "a", "bins": [0, 1]},
            ],
        )
        assert isinstance(rs.aggregations[0], StatisticsDefinition)
        assert isinstance(rs.aggregations[1], Histogram1DDefinition)

    def test_roundtrip_serialization(self, report_state):
        dumped = report_state.model_dump()
        restored = ReportState.model_validate(dumped)
        assert restored.name == report_state.name
        assert isinstance(restored.aggregations[0], Histogram1DDefinition)


def test_wizard_order_matches_enum():
    assert WIZARD_ORDER == list(WizardStep)
    assert WIZARD_ORDER[0] == WizardStep.SOURCE_DATA
    assert WIZARD_ORDER[-1] == WizardStep.READY
