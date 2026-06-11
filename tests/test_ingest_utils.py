"""Tests for the pure data-transform helpers in ingest/utils/utils.py.

That module imports pyspark and delta at the top, which aren't installed here
(nor in CI). We stub those heavy modules so the file can be imported, then test
the genuinely pure functions that depend only on numpy/builtins:
`_replicate_signals` and `_create_data_groups`.

The Spark/Delta/dbutils helpers (update_status, upsert_set, get_files_by_status,
table_exists, convert_obd_data, ...) need a live Spark runtime and are out of
scope for unit tests.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest


def _ensure_stub(name: str, **attrs) -> None:
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


# Satisfy the module-level `import pyspark.sql.functions as F`,
# `from pyspark.sql import DataFrame`, and `from delta.tables import DeltaTable`.
try:  # pragma: no cover - exercised only when pyspark is genuinely installed
    import pyspark  # noqa: F401
except ImportError:
    _ensure_stub("pyspark")
    _ensure_stub("pyspark.sql", DataFrame=type("DataFrame", (), {}))
    _ensure_stub("pyspark.sql.functions")
    sys.modules["pyspark"].sql = sys.modules["pyspark.sql"]

try:  # pragma: no cover
    import delta  # noqa: F401
except ImportError:
    _ensure_stub("delta.tables", DeltaTable=type("DeltaTable", (), {}))
    _ensure_stub("delta", tables=sys.modules["delta.tables"])


def _load_utils():
    path = os.path.join(os.path.dirname(__file__), "..", "ingest", "utils", "utils.py")
    spec = importlib.util.spec_from_file_location("ingest_utils_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


utils = _load_utils()


class TestReplicateSignals:
    def test_zero_replication_returns_input_unchanged(self):
        master = [0, 10, 20]
        signals = {"a": [1.0, 2.0, 3.0]}
        out_master, out_signals = utils._replicate_signals(master, signals, 0)
        assert out_master == [0, 10, 20]
        assert out_signals == {"a": [1.0, 2.0, 3.0]}

    def test_single_replication_appends_shifted_copy(self):
        master = [0, 10, 20]
        signals = {"a": [1.0, 2.0, 3.0]}
        out_master, out_signals = utils._replicate_signals(master, signals, 1)
        # second block is the original shifted by the last timestamp (20)
        assert out_master == [0, 10, 20, 20, 30, 40]
        assert out_signals["a"] == [1.0, 2.0, 3.0, 1.0, 2.0, 3.0]

    def test_length_grows_linearly_with_replication_factor(self):
        master = [0, 1, 2]
        signals = {"a": [0.0, 0.0, 0.0], "b": [1.0, 1.0, 1.0]}
        out_master, out_signals = utils._replicate_signals(master, signals, 3)
        assert len(out_master) == 3 * (3 + 1)
        for v in out_signals.values():
            assert len(v) == 3 * (3 + 1)

    def test_does_not_mutate_input_signals(self):
        master = [0, 10]
        signals = {"a": [1.0, 2.0]}
        utils._replicate_signals(master, signals, 2)
        assert signals == {"a": [1.0, 2.0]}


class TestCreateDataGroups:
    def test_partitions_all_signals_without_loss(self, monkeypatch):
        # Force a deterministic group count.
        monkeypatch.setattr(utils.np.random, "randint", lambda lo, hi: 3)
        signals = {f"s{i}": [float(i)] for i in range(7)}
        groups = utils._create_data_groups(signals)

        assert len(groups) == 3
        merged: dict = {}
        for g in groups:
            merged.update(g)
        assert merged.keys() == signals.keys()
        # every signal placed exactly once
        total = sum(len(g) for g in groups)
        assert total == len(signals)

    def test_group_count_is_within_expected_range(self):
        # Real randint over many trials stays in [1, 9].
        signals = {f"s{i}": [0.0] for i in range(5)}
        for _ in range(25):
            groups = utils._create_data_groups(signals)
            assert 1 <= len(groups) <= 9
            merged: dict = {}
            for g in groups:
                merged.update(g)
            assert merged.keys() == signals.keys()
