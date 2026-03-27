"""Ingest endpoints — /api/ingest/*

Trigger and monitor the MF4-to-Silver ingest pipeline as a Databricks job run.
Reuses Jonathan's timeseries_ingest_solution_accelerator notebooks (copied to ingest/).
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request

from server.agent import _sessions
from server.config import IS_DATABRICKS_APP, get_workspace_client
from server.models import IngestStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

def _get_ingest_notebook_root() -> str:
    """Resolve the workspace path to the ingest notebooks.

    The notebooks must live in a workspace location where they are imported as
    NOTEBOOK objects (not files). The ``databricks sync`` command handles this
    when the source files start with ``# Databricks notebook source``.

    The app SP needs CAN_READ on this workspace folder — granted once during
    setup via ``permissions.set('directories', ...)``.
    """
    return os.environ.get(
        "INGEST_NOTEBOOK_ROOT",
        "/Workspace/Users/maxim.hammer@databricks.com/impulse-app/ingest",
    )


def _get_client(request: Request):
    if IS_DATABRICKS_APP:
        from databricks.sdk import WorkspaceClient

        token = request.headers.get("X-Forwarded-Access-Token")
        if token:
            host = os.environ.get("DATABRICKS_HOST", "")
            return WorkspaceClient(host=host, token=token)
        return WorkspaceClient()
    return get_workspace_client()


INGEST_CLUSTER_KEY = "ingest_cluster"


def _build_ingest_job(
    nb_root: str,
    catalog: str,
    schema: str,
    mdf4_volume: str,
    source_catalog: str = "",
    source_schema: str = "",
    session_id: str = "",
) -> dict:
    """Build the full job definition for the ingest pipeline.

    Uses jobs.create() + jobs.run_now() with a shared job_cluster instead of
    jobs.submit() with new_cluster per task — the latter has reliability issues
    with ephemeral clusters on some workspaces.
    """
    from databricks.sdk.service.compute import (
        AwsAttributes,
        ClusterSpec,
        DataSecurityMode,
        Library,
        PythonPyPiLibrary,
    )
    from databricks.sdk.service.jobs import (
        ConditionTask,
        ConditionTaskOp,
        JobCluster,
        NotebookTask,
        RunIf,
        Source,
        Task,
        TaskDependency,
    )

    params = {
        "catalog": catalog,
        "schema": schema,
        "source_catalog": source_catalog or catalog,
        "source_schema": source_schema or schema,
        "mdf4_volume": mdf4_volume,
        "checkpoint_volume": "mdf4_checkpoint",
        "reset": "False",
        "max_datapoints_per_bin": "1000000",
        "reprocess_current_run": "True",
        "reprocess_last_failed_run": "True",
        "signal_replication_factor": "0",
        "max_batch_size": "100",
    }

    libs = [
        Library(pypi=PythonPyPiLibrary(package="asammdf<8")),
        Library(pypi=PythonPyPiLibrary(package="binpacking")),
    ]

    node_type = os.environ.get("INGEST_NODE_TYPE", "i3.xlarge")
    cluster_spec = ClusterSpec(
        spark_version="15.4.x-scala2.12",
        node_type_id=node_type,
        num_workers=2,
        data_security_mode=DataSecurityMode.SINGLE_USER,
        aws_attributes=AwsAttributes(first_on_demand=1),
    )

    job_cluster = JobCluster(
        job_cluster_key=INGEST_CLUSTER_KEY,
        new_cluster=cluster_spec,
    )

    def _dep(keys: list[str]) -> list[TaskDependency]:
        return [TaskDependency(task_key=k) for k in keys]

    def _nb(key: str, nb: str, depends: list[str] | None = None, run_if: RunIf = RunIf.ALL_SUCCESS) -> Task:
        nb_path = nb.removesuffix(".py")
        return Task(
            task_key=key,
            notebook_task=NotebookTask(
                notebook_path=f"{nb_root}/ingest_mdf/{nb_path}",
                base_parameters=params,
                source=Source.WORKSPACE,
            ),
            depends_on=_dep(depends) if depends else None,
            libraries=libs,
            job_cluster_key=INGEST_CLUSTER_KEY,
            run_if=run_if,
        )

    tasks = [
        _nb("setup_tables", "a_setup_tables.py"),
        _nb("detect_new_files", "b_detect_new_files.py", depends=["setup_tables"]),
        _nb("get_next_batch", "c_get_next_batch.py", depends=["detect_new_files"]),
        Task(
            task_key="check_data_availability",
            depends_on=_dep(["get_next_batch"]),
            run_if=RunIf.ALL_SUCCESS,
            condition_task=ConditionTask(
                op=ConditionTaskOp.NOT_EQUAL,
                left="{{tasks.[get_next_batch].values.[next_run_id]}}",
                right="noop",
            ),
        ),
        Task(
            task_key="mdf_to_delta",
            notebook_task=NotebookTask(
                notebook_path=f"{nb_root}/ingest_mdf/c_mdf_to_delta",
                base_parameters=params,
                source=Source.WORKSPACE,
            ),
            depends_on=[TaskDependency(task_key="check_data_availability", outcome="true")],
            libraries=libs,
            job_cluster_key=INGEST_CLUSTER_KEY,
            run_if=RunIf.ALL_SUCCESS,
        ),
        _nb("analytical_layer", "d_analytical_layer.py", depends=["mdf_to_delta"]),
        _nb("channel_metadata", "e_channel_metadata.py", depends=["mdf_to_delta"]),
        _nb("container_metadata", "f_container_metadata.py", depends=["analytical_layer", "channel_metadata"]),
        _nb("conversion_succeeded", "g_update_processing_status_succeeded.py", depends=["container_metadata"]),
        _nb("conversion_failed", "g_update_processing_status_failed.py",
            depends=["container_metadata", "mdf_to_delta", "channel_metadata", "analytical_layer"],
            run_if=RunIf.AT_LEAST_ONE_FAILED),
    ]

    return {
        "job_clusters": [job_cluster],
        "tasks": tasks,
        "name": f"impulse-ingest-{session_id[:8]}",
        "timeout_seconds": 3600,
    }


@router.post("/trigger/{session_id}")
async def trigger_ingest(session_id: str, request: Request):
    """Create a job and trigger a run for the MF4-to-Silver ingest pipeline."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    sd = session.state.source_data
    if not sd.upload_volume_path:
        raise HTTPException(400, "No files uploaded yet.")
    if not sd.silver_catalog or not sd.silver_schema:
        raise HTTPException(400, "Silver layer destination not configured.")

    # Reset previous run state so retries work
    sd.ingest_run_id = None
    sd.ingest_status = IngestStatus.NOT_STARTED

    w = _get_client(request)

    nb_root = _get_ingest_notebook_root()
    logger.info("Using ingest notebook root: %s", nb_root)

    job_def = _build_ingest_job(
        nb_root=nb_root,
        catalog=sd.silver_catalog,
        schema=sd.silver_schema,
        mdf4_volume=sd.upload_volume,
        source_catalog=sd.upload_catalog,
        source_schema=sd.upload_schema,
        session_id=session_id,
    )

    try:
        job = w.jobs.create(**job_def)
        logger.info("Created ingest job %s for session %s", job.job_id, session_id)

        run = w.jobs.run_now(job.job_id)
        run_id = run.run_id
        sd.ingest_run_id = run_id
        sd.ingest_status = IngestStatus.RUNNING
        logger.info("Triggered ingest run %s for job %s", run_id, job.job_id)

        # Fetch run URL immediately
        run_url = ""
        try:
            run_info = w.jobs.get_run(run_id)
            run_url = run_info.run_page_url or ""
        except Exception:
            pass
    except Exception as e:
        logger.exception("Failed to create/run ingest job")
        raise HTTPException(502, f"Failed to submit ingest job: {e}")

    return {
        "run_id": run_id,
        "run_url": run_url,
        "report_state": session.state.model_dump(),
    }


@router.get("/status/{session_id}")
async def ingest_status(session_id: str, request: Request):
    """Check the status of the ingest pipeline run."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    sd = session.state.source_data
    if not sd.ingest_run_id:
        return {
            "status": "not_started",
            "tasks": [],
            "report_state": session.state.model_dump(),
        }

    w = _get_client(request)

    try:
        run = w.jobs.get_run(sd.ingest_run_id)
    except Exception as e:
        logger.exception("Failed to get run %s", sd.ingest_run_id)
        raise HTTPException(502, f"Failed to get run status: {e}")

    life_cycle = run.state.life_cycle_state.value if run.state and run.state.life_cycle_state else "UNKNOWN"
    result_state = run.state.result_state.value if run.state and run.state.result_state else None

    tasks_status = []
    for t in run.tasks or []:
        t_life = t.state.life_cycle_state.value if t.state and t.state.life_cycle_state else "PENDING"
        t_result = t.state.result_state.value if t.state and t.state.result_state else None
        tasks_status.append({
            "task_key": t.task_key,
            "life_cycle_state": t_life,
            "result_state": t_result,
        })

    run_url = run.run_page_url or ""

    if result_state == "SUCCESS":
        sd.ingest_status = IngestStatus.SUCCEEDED
        # Auto-populate data sources from the silver layer
        from server.routes.state import _auto_populate_silver_data_sources
        _auto_populate_silver_data_sources(session)
    elif result_state in ("FAILED", "TIMEDOUT", "CANCELED"):
        sd.ingest_status = IngestStatus.FAILED
    else:
        sd.ingest_status = IngestStatus.RUNNING

    elapsed = 0
    if run.start_time and run.end_time:
        elapsed = int((run.end_time - run.start_time) / 1000)
    elif run.start_time:
        import time
        elapsed = int(time.time() - run.start_time / 1000)

    return {
        "status": sd.ingest_status.value,
        "life_cycle_state": life_cycle,
        "result_state": result_state,
        "run_url": run_url,
        "elapsed_seconds": elapsed,
        "tasks": tasks_status,
        "report_state": session.state.model_dump(),
    }
