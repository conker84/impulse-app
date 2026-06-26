"""MLflow Tracing for the LLM agent.

Tracing is OFF until `init_tracing()` runs at app startup, so tests and local
runs that never call it produce no traces and pay no overhead. We use manual
spans (not the `@mlflow.trace` decorator) on purpose: the agent functions take
the user's OBO token and a large ReportState, and we must never capture those
in a span. Spans here record only safe inputs/outputs.

OpenAI calls are traced automatically via `mlflow.openai.autolog()` and nest
under the manual root span, giving per-turn token usage and latency.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    import mlflow  # noqa: F401
    _HAS_MLFLOW = True
except Exception:  # pragma: no cover - mlflow optional
    mlflow = None
    _HAS_MLFLOW = False

_ENABLED = False


def init_tracing() -> None:
    """Enable MLflow tracing. Call once at app startup."""
    global _ENABLED
    if not _HAS_MLFLOW:
        logger.info("mlflow not installed; agent tracing disabled")
        return
    if os.environ.get("MLFLOW_TRACING_ENABLED", "true").lower() != "true":
        logger.info("MLFLOW_TRACING_ENABLED is not 'true'; agent tracing disabled")
        return
    try:
        mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "databricks"))
        mlflow.set_experiment(os.environ.get("MLFLOW_EXPERIMENT", "/Shared/impulse-agent-traces"))
        mlflow.openai.autolog()
        _ENABLED = True
        logger.info("MLflow agent tracing enabled")
    except Exception as e:  # never let observability break the app
        logger.warning("Could not enable MLflow tracing: %s", e)


def enabled() -> bool:
    return _ENABLED


@contextmanager
def span(name: str, span_type: str = "UNKNOWN", inputs: dict | None = None):
    """A no-op context manager unless tracing is enabled. Yields the span (or None)."""
    if not _ENABLED:
        yield None
        return
    try:
        with mlflow.start_span(name=name, span_type=span_type) as s:
            if inputs is not None:
                try:
                    s.set_inputs(inputs)
                except Exception:
                    pass
            yield s
    except Exception as e:  # tracing must never break the request
        logger.debug("span(%s) failed: %s", name, e)
        yield None


def set_outputs(s, outputs: dict) -> None:
    if s is None:
        return
    try:
        s.set_outputs(outputs)
    except Exception:
        pass


def set_tags(tags: dict) -> None:
    if not _ENABLED:
        return
    try:
        mlflow.update_current_trace(tags=tags)
    except Exception:
        pass


def span_trace_id(s) -> str | None:
    """The trace id of a span, to hand back to the client for feedback."""
    if s is None:
        return None
    try:
        return s.trace_id
    except Exception:
        return getattr(s, "request_id", None)


def log_feedback(trace_id: str | None, positive: bool, comment: str | None = None,
                 user: str | None = None) -> bool:
    """Attach a 👍/👎 (+ optional comment) to a trace. Returns True if recorded."""
    if not (_HAS_MLFLOW and trace_id):
        return False
    try:
        from mlflow.entities import AssessmentSource, AssessmentSourceType
        mlflow.log_feedback(
            trace_id=trace_id,
            name="user_feedback",
            value=bool(positive),
            rationale=comment or None,
            source=AssessmentSource(
                source_type=AssessmentSourceType.HUMAN, source_id=user or "user"
            ),
        )
        return True
    except Exception as e:
        logger.warning("log_feedback failed for trace %s: %s", trace_id, e)
        return False
