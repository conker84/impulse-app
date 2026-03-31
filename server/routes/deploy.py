"""Deploy endpoints — /api/scaffold, /api/deploy, /api/deploy/status

Scaffold report from template, upload files to workspace via SDK,
create and run a Databricks job via the Jobs API, and monitor runs.

Authentication: All workspace operations use the app service principal
(in deployed mode) or the local profile (in dev mode). The job is
created with ``run_as`` set to the logged-in user so it executes with
the user's Unity Catalog permissions — no PAT storage needed.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import time

from fastapi import APIRouter, HTTPException, Request

from server.agent import _sessions
from server.code_generator import generate_all_files
from server.config import (
    DATABRICKS_PROFILE,
    IS_DATABRICKS_APP,
    REPORTS_ROOT,
    TEMPLATE_ROOT,
    get_workspace_client,
)
from server.models import DeploymentStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["deploy"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_email(request: Request) -> str:
    """Resolve user email from X-Forwarded-Email header."""
    if not IS_DATABRICKS_APP:
        return ""
    email = request.headers.get("X-Forwarded-Email", "")
    if not email:
        raise HTTPException(401, "Missing X-Forwarded-Email header")
    return email


def _get_session_state(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session.state


def _user_report_dir(user_email: str, report_name: str) -> str:
    """Build per-user report directory: REPORTS_ROOT/<user_folder>/<report_name>."""
    user_folder = (user_email or "local").split("@")[0].replace(".", "_").replace("+", "_")
    return os.path.join(REPORTS_ROOT, user_folder, report_name)


def _profile_args() -> list[str]:
    """Return CLI profile args — empty on Databricks App."""
    if IS_DATABRICKS_APP:
        return []
    return ["--profile", DATABRICKS_PROFILE]


# ---------------------------------------------------------------------------
# Scaffold helpers (template expansion)
# ---------------------------------------------------------------------------

def _scaffold_env() -> dict[str, str]:
    """Minimal env for ``databricks bundle init`` (local template, no auth needed)."""
    env = os.environ.copy()
    if "HOME" not in env:
        env["HOME"] = "/tmp"
    return env


def _strip_txt_suffix(report_dir: str) -> None:
    """Remove the .txt guard suffix from template files."""
    for dirpath, _, filenames in os.walk(report_dir):
        for fname in filenames:
            if fname.endswith((".ipynb.txt", ".py.txt")):
                old = os.path.join(dirpath, fname)
                os.rename(old, old[: -len(".txt")])


def _apply_all_purpose_cluster(report_dir: str) -> None:
    """Modify jobs.yml to run report_generation on an existing all-purpose cluster."""
    jobs_path = os.path.join(report_dir, "resources", "jobs.yml")
    if not os.path.isfile(jobs_path):
        return

    with open(jobs_path) as f:
        lines = f.readlines()

    new_lines: list[str] = []
    for i, line in enumerate(lines):
        new_lines.append(line)
        if line.strip() == "- task_key: report_generation":
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                indent = next_line[: len(next_line) - len(next_line.lstrip())]
            else:
                indent = "          "
            new_lines.append(f"{indent}existing_cluster_id: ${{var.existing_cluster_id}}\n")

    with open(jobs_path, "w") as f:
        f.writelines(new_lines)
    logger.info("Patched jobs.yml for all-purpose cluster")


# ---------------------------------------------------------------------------
# Workspace upload
# ---------------------------------------------------------------------------

def _upload_report_to_workspace(report_dir: str, ws_root: str) -> None:
    """Upload all report files from local filesystem to workspace.

    Uses the app service principal (deployed) or local profile (dev).
    Skips DAB-specific files not needed for job execution.
    """
    from databricks.sdk.service.workspace import ImportFormat, Language

    w = get_workspace_client()
    w.workspace.mkdirs(ws_root)

    skip_dirs = {".databricks", "tests", "resources", "__pycache__"}
    skip_files = {"databricks.yml", "pyproject.toml", ".gitignore",
                  ".python-version", "README.md", "azure-pipelines.yaml"}

    for dirpath, dirnames, filenames in os.walk(report_dir):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]

        for fname in filenames:
            if fname in skip_files:
                continue

            local_path = os.path.join(dirpath, fname)
            rel = os.path.relpath(local_path, report_dir)
            ws_path = f"{ws_root}/{rel}"

            w.workspace.mkdirs(os.path.dirname(ws_path))

            with open(local_path, "rb") as f:
                content = f.read()

            encoded = base64.b64encode(content).decode()

            if fname.endswith(".py"):
                w.workspace.import_(
                    path=ws_path,
                    content=encoded,
                    format=ImportFormat.SOURCE,
                    language=Language.PYTHON,
                    overwrite=True,
                )
            elif fname.endswith(".ipynb"):
                w.workspace.import_(
                    path=ws_path,
                    content=encoded,
                    format=ImportFormat.JUPYTER,
                    overwrite=True,
                )
            else:
                w.workspace.import_(
                    path=ws_path,
                    content=encoded,
                    format=ImportFormat.AUTO,
                    overwrite=True,
                )

            logger.debug("Uploaded %s → %s", rel, ws_path)

    logger.info("Uploaded report to workspace: %s", ws_root)


# ---------------------------------------------------------------------------
# Job definition builder
# ---------------------------------------------------------------------------

def _find_wheel(report_dir: str) -> str | None:
    """Find the framework wheel filename in the report's lib/ directory."""
    lib_dir = os.path.join(report_dir, "lib")
    if not os.path.isdir(lib_dir):
        return None
    for f in os.listdir(lib_dir):
        if f.endswith(".whl"):
            return f
    return None


def _build_report_job(
    report_name: str,
    ws_root: str,
    report_dir: str,
    state,
    user_email: str,
) -> dict:
    """Build a job definition matching the DAB template structure."""
    from databricks.sdk.service.jobs import (
        Environment,
        JobEnvironment,
        JobParameter,
        JobRunAs,
        NotebookTask,
        Source,
        Task,
        TaskDependency,
    )

    config_from_src = "./config/dev_config.json"
    config_from_subdir = "../config/dev_config.json"

    tasks = [
        Task(
            task_key="pre_processing",
            notebook_task=NotebookTask(
                notebook_path=f"{ws_root}/src/preprocessing/01_status_pre-processing.ipynb",
                base_parameters={"config_path": config_from_subdir},
                source=Source.WORKSPACE,
            ),
            environment_key="impulse",
        ),
        Task(
            task_key="report_generation",
            depends_on=[TaskDependency(task_key="pre_processing")],
            notebook_task=NotebookTask(
                notebook_path=f"{ws_root}/src/report.py",
                base_parameters={"config_path": config_from_src},
                source=Source.WORKSPACE,
            ),
            environment_key="impulse",
        ),
        Task(
            task_key="post_processing",
            depends_on=[TaskDependency(task_key="report_generation")],
            notebook_task=NotebookTask(
                notebook_path=f"{ws_root}/src/postprocessing/01_status_post-processing_success.ipynb",
                base_parameters={"config_path": config_from_subdir},
                source=Source.WORKSPACE,
            ),
            environment_key="impulse",
        ),
    ]

    if state.use_all_purpose_cluster and state.all_purpose_cluster_id:
        tasks[1].existing_cluster_id = state.all_purpose_cluster_id

    wheel_fname = _find_wheel(report_dir)
    dependencies: list[str] = []
    if wheel_fname:
        dependencies.append(f"{ws_root}/lib/{wheel_fname}")

    environments = [
        JobEnvironment(
            environment_key="impulse",
            spec=Environment(client="5", dependencies=dependencies),
        ),
    ]

    job_kwargs: dict = {
        "name": f"[impulse] {report_name}",
        "tasks": tasks,
        "environments": environments,
        "parameters": [
            JobParameter(name="reset_report", default="false"),
            JobParameter(name="status_table_name", default="status"),
        ],
        "timeout_seconds": 7200,
    }

    if user_email:
        job_kwargs["run_as"] = JobRunAs(user_name=user_email)

    return job_kwargs


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/scaffold/{session_id}")
async def scaffold_report(session_id: str, request: Request):
    """Scaffold a new report from the template, then overwrite with generated code."""
    user_email = _get_user_email(request)
    state = _get_session_state(session_id)

    if not state.name:
        raise HTTPException(400, "Report name not set. Use set_report_metadata first.")

    if state.use_all_purpose_cluster and not state.all_purpose_cluster_id:
        raise HTTPException(
            400,
            "All-purpose cluster mode is selected but no Cluster ID is configured. "
            "Please set a Cluster ID in Settings (gear icon) or switch to Serverless mode.",
        )

    user_dir = os.path.join(
        REPORTS_ROOT,
        (user_email or "local").split("@")[0].replace(".", "_").replace("+", "_"),
    )
    os.makedirs(user_dir, exist_ok=True)

    report_dir = _user_report_dir(user_email, state.name)
    if os.path.exists(report_dir):
        shutil.rmtree(report_dir)
        logger.info("Removed existing report folder %s for re-scaffold", report_dir)

    ws_host = get_workspace_client().config.host

    config = {
        "report_name": state.name,
        "dev_host": os.environ.get("DAB_DEV_HOST", ws_host),
        "dev_group": os.environ.get("DAB_DEV_GROUP", "users"),
        "stg_host": os.environ.get("DAB_STG_HOST", ws_host),
        "stg_group": os.environ.get("DAB_STG_GROUP", "users"),
        "prd_host": os.environ.get("DAB_PRD_HOST", ws_host),
        "prd_group": os.environ.get("DAB_PRD_GROUP", "users"),
        "prd_sp_name": os.environ.get("DAB_PRD_SP_NAME", ""),
    }

    config_path = os.path.join(user_dir, f"config_{state.name}.json")
    with open(config_path, "w") as f:
        json.dump(config, f)

    try:
        subprocess.run(
            [
                "databricks", "bundle", "init", TEMPLATE_ROOT,
                "--output-dir", state.name,
                "--config-file", f"config_{state.name}.json",
                *_profile_args(),
            ],
            cwd=user_dir,
            capture_output=True,
            text=True,
            check=True,
            env=_scaffold_env(),
        )
    except subprocess.CalledProcessError as e:
        detail = e.stderr or e.stdout or f"exit code {e.returncode}"
        raise HTTPException(500, f"Scaffold failed: {detail}")
    finally:
        if os.path.exists(config_path):
            os.remove(config_path)

    _strip_txt_suffix(report_dir)

    generated = generate_all_files(state)
    for rel_path, content in generated.items():
        full_path = os.path.join(report_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)

    if state.use_all_purpose_cluster and state.all_purpose_cluster_id:
        _apply_all_purpose_cluster(report_dir)

    state.deployment = DeploymentStatus.SCAFFOLDING

    try:
        from server.report_store import save_report
        save_report(user_email, state)
        logger.info("Auto-saved report '%s' for %s after scaffold", state.name, user_email)
    except Exception:
        logger.warning("Auto-save after scaffold failed (non-fatal)", exc_info=True)

    return {"status": "scaffolded", "report_dir": report_dir, "files": list(generated.keys())}


@router.post("/deploy/{session_id}")
async def deploy_and_run(session_id: str, request: Request):
    """Upload report to workspace, create a job, and trigger a run.

    Uses the app service principal for workspace upload and job creation.
    The job's ``run_as`` is set to the logged-in user so notebook code
    executes with the user's Unity Catalog permissions.
    """
    user_email = _get_user_email(request)
    state = _get_session_state(session_id)
    report_dir = _user_report_dir(user_email, state.name)

    if not os.path.exists(report_dir):
        raise HTTPException(400, "Report not scaffolded yet. Call /api/scaffold first.")

    state.deployment = DeploymentStatus.DEPLOYING

    try:
        # 1. Upload files to workspace
        # Upload to the SP's own workspace directory — the SP always has
        # write access to /Users/{its-own-client-id}/ without extra grants.
        sp_client_id = w.config.client_id or w.current_user.me().user_name
        user_folder = (user_email or "unknown").split("@")[0].replace(".", "_")
        ws_root = f"/Users/{sp_client_id}/impulse-reports/{user_folder}/{state.name}"
        _upload_report_to_workspace(report_dir, ws_root)

        # 2. Create the job
        w = get_workspace_client()
        job_kwargs = _build_report_job(
            report_name=state.name,
            ws_root=ws_root,
            report_dir=report_dir,
            state=state,
            user_email=user_email,
        )

        try:
            job = w.jobs.create(**job_kwargs)
        except Exception as e:
            if "run_as" in str(e).lower() or "permission" in str(e).lower():
                logger.warning(
                    "Could not set run_as=%s — job will run as app SP. Error: %s",
                    user_email, e,
                )
                job_kwargs.pop("run_as", None)
                job = w.jobs.create(**job_kwargs)
            else:
                raise

        logger.info("Created job %s (%s) for report '%s'", job.job_id, job_kwargs["name"], state.name)

        # 3. Trigger the run
        run = w.jobs.run_now(job.job_id)
        run_id = run.run_id

        # 4. Fetch run URL
        run_info = w.jobs.get_run(run_id)
        run_url = run_info.run_page_url or ""

        # 5. Update state
        state.deployment = DeploymentStatus.RUNNING
        state.deploy_started_at = time.time()
        state.user_email = user_email
        state.run_id = str(run_id)
        state.run_url = run_url
        state.job_id = str(job.job_id)

        logger.info("Triggered run %s for job %s — %s", run_id, job.job_id, run_url)

    except HTTPException:
        raise
    except Exception as e:
        state.deployment = DeploymentStatus.FAILED
        logger.exception("Deploy failed for report '%s'", state.name)
        raise HTTPException(500, f"Deploy failed: {e}")

    return {
        "status": "running",
        "message": "Report job has been submitted. You can track the progress below.",
        "run_url": run_url,
    }


@router.post("/deploy/cancel/{session_id}")
async def cancel_run(session_id: str):
    """Cancel a running job."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    state = session.state

    if not state.run_id:
        raise HTTPException(400, "No run to cancel.")

    try:
        w = get_workspace_client()
        w.jobs.cancel_run(int(state.run_id))
        state.deployment = DeploymentStatus.FAILED
        logger.info("Cancelled run %s for session %s", state.run_id, session_id)
        return {"status": "cancelled", "message": "Job run cancelled."}
    except Exception as e:
        logger.exception("Failed to cancel run %s", state.run_id)
        raise HTTPException(502, f"Failed to cancel run: {e}")


@router.get("/deploy/status/{session_id}")
async def deploy_status(session_id: str):
    """Poll job run status."""
    session = _sessions.get(session_id)
    if not session:
        return {
            "status": "failed",
            "elapsed_seconds": 0,
            "run_url": None,
            "tasks": [],
            "message": "Session lost (server may have restarted). Please start a new report.",
        }
    state = session.state

    elapsed_seconds = 0
    if state.deploy_started_at:
        elapsed_seconds = int(time.time() - state.deploy_started_at)

    base = {
        "status": state.deployment.value,
        "elapsed_seconds": elapsed_seconds,
        "run_url": state.run_url,
    }

    if not state.run_id:
        return {**base, "tasks": [], "message": "Job is starting..."}

    try:
        w = get_workspace_client()
        run = w.jobs.get_run(int(state.run_id))
    except Exception:
        logger.exception("Failed to fetch run status")
        return {**base, "tasks": [], "message": "Waiting for run details..."}

    result_state = None
    life_cycle_state = None
    if run.state:
        if run.state.result_state:
            result_state = run.state.result_state.value
        if run.state.life_cycle_state:
            life_cycle_state = run.state.life_cycle_state.value

    tasks_status = []
    if run.tasks:
        for t in run.tasks:
            ts = t.state
            tasks_status.append({
                "task_key": t.task_key,
                "result_state": ts.result_state.value if ts and ts.result_state else None,
                "life_cycle_state": ts.life_cycle_state.value if ts and ts.life_cycle_state else None,
            })

    if result_state == "SUCCESS":
        state.deployment = DeploymentStatus.COMPLETED
    elif result_state in ("FAILED", "TIMEDOUT", "CANCELED"):
        state.deployment = DeploymentStatus.FAILED
    elif life_cycle_state in ("PENDING", "RUNNING", "QUEUED", "BLOCKED"):
        state.deployment = DeploymentStatus.RUNNING

    return {
        **base,
        "status": state.deployment.value,
        "result_state": result_state,
        "life_cycle_state": life_cycle_state,
        "tasks": tasks_status,
    }
