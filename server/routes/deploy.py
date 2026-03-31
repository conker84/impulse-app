"""Deploy endpoints — /api/scaffold, /api/deploy, /api/deploy/status

Scaffold report using create-report skill, deploy via databricks-asset-bundles skill,
and monitor job runs via validate-report-execution skill step 3.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time

from fastapi import APIRouter, HTTPException, Request

from server.agent import _sessions
from server.code_generator import generate_all_files
from server.config import DATABRICKS_PROFILE, IS_DATABRICKS_APP, REPORTS_ROOT, TEMPLATE_ROOT, get_workspace_client
from server.models import DeploymentStatus

logger = logging.getLogger(__name__)


def _cli_env(user_email: str | None, user_token: str | None = None) -> dict[str, str]:
    """Build env dict for Databricks CLI subprocesses.

    On Databricks App: uses the forwarded OBO token (X-Forwarded-Access-Token)
    from the logged-in user's session. The token carries ``all-apis`` scope
    via the app's custom OAuth integration, covering Jobs, Workspace, and all
    other Databricks APIs.
    Locally: inherits the environment as-is (profile from ~/.databrickscfg).
    """
    env = os.environ.copy()
    if "HOME" not in env:
        env["HOME"] = "/tmp"
    if IS_DATABRICKS_APP:
        if not user_token:
            raise HTTPException(
                401,
                "Deploy requires User Authorization to be enabled on this app. "
                "Ask a workspace admin to enable 'User token passthrough' in Admin Settings.",
            )
        logger.info("_cli_env: user_email=%s, using forwarded OBO token", user_email)
        env["DATABRICKS_TOKEN"] = user_token
        env.pop("DATABRICKS_CLIENT_ID", None)
        env.pop("DATABRICKS_CLIENT_SECRET", None)
    return env


def _get_user_email(request: Request) -> str:
    """Resolve user email from X-Forwarded-Email header."""
    if not IS_DATABRICKS_APP:
        return ""
    email = request.headers.get("X-Forwarded-Email", "")
    if not email:
        raise HTTPException(401, "Missing X-Forwarded-Email header")
    return email


def _get_polling_client():
    """Return a WorkspaceClient for job status polling and cancellation.

    Uses the app service principal (deployed) or local profile (dev).
    The SP can read status and cancel runs for jobs created by the user
    via the app since the user is the job owner.
    """
    return get_workspace_client()


def _profile_args() -> list[str]:
    """Return CLI profile args — empty on Databricks App."""
    if IS_DATABRICKS_APP:
        return []
    return ["--profile", DATABRICKS_PROFILE]

def _strip_txt_suffix(report_dir: str) -> None:
    """Remove the .txt guard suffix that was added before workspace import.

    Template .ipynb and .py files are stored with a .txt suffix so that
    workspace import-dir treats them as plain files instead of converting
    them to Databricks notebooks. After scaffold copies them, we strip
    the .txt to restore the original extension.
    """
    for dirpath, _, filenames in os.walk(report_dir):
        for fname in filenames:
            if fname.endswith((".ipynb.txt", ".py.txt")):
                old = os.path.join(dirpath, fname)
                os.rename(old, old[: -len(".txt")])


def _apply_all_purpose_cluster(report_dir: str) -> None:
    """Modify jobs.yml to run report_generation on an existing all-purpose cluster.

    The template defaults to serverless (no cluster config on the task).
    This patches in ``existing_cluster_id: ${var.existing_cluster_id}``
    so the DAB variable controls which cluster is used.
    """
    jobs_path = os.path.join(report_dir, "resources", "jobs.yml")
    if not os.path.isfile(jobs_path):
        logger.warning("jobs.yml not found at %s — skipping cluster swap", jobs_path)
        return

    with open(jobs_path) as f:
        lines = f.readlines()

    new_lines: list[str] = []
    for i, line in enumerate(lines):
        new_lines.append(line)
        if line.strip() == "- task_key: report_generation":
            # Find the indentation of the next line (depends_on) to match it
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                indent = next_line[: len(next_line) - len(next_line.lstrip())]
            else:
                indent = "          "
            new_lines.append(f"{indent}existing_cluster_id: ${{var.existing_cluster_id}}\n")

    with open(jobs_path, "w") as f:
        f.writelines(new_lines)
    logger.info("Patched jobs.yml to use existing_cluster_id for report_generation")


router = APIRouter(prefix="/api", tags=["deploy"])


def _get_session_state(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session.state


def _user_report_dir(user_email: str, report_name: str) -> str:
    """Build per-user report directory: REPORTS_ROOT/<user_folder>/<report_name>.

    Sanitises the email to produce a filesystem-safe folder name.
    """
    user_folder = (user_email or "local").split("@")[0].replace(".", "_").replace("+", "_")
    return os.path.join(REPORTS_ROOT, user_folder, report_name)


@router.post("/scaffold/{session_id}")
async def scaffold_report(session_id: str, request: Request):
    """Scaffold a new report from the template, then overwrite with generated code."""
    # Debug: log forwarded headers to diagnose OBO token issues
    fwd_token = request.headers.get("X-Forwarded-Access-Token")
    fwd_email = request.headers.get("X-Forwarded-Email")
    logger.info(
        "scaffold: X-Forwarded-Email=%s, has_X-Forwarded-Access-Token=%s, headers=%s",
        fwd_email, bool(fwd_token),
        [k for k in request.headers.keys() if "forward" in k.lower() or "auth" in k.lower()],
    )
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

    user_dir = os.path.join(REPORTS_ROOT, (user_email or "local").split("@")[0].replace(".", "_").replace("+", "_"))
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
            env=_cli_env(user_email, user_token=request.headers.get("X-Forwarded-Access-Token")),
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


_RUN_URL_RE = re.compile(r"https://[^\s]+#job/\d+/run/\d+")
_RUN_ID_RE = re.compile(r"/run/(\d+)")


def _background_bundle_run(
    session_id: str,
    report_dir: str,
    env: dict,
    state_name: str,
    var_args: list[str] | None = None,
):
    """Run `databricks bundle run` in a background thread, streaming output to capture run URL early."""
    state = _get_session_state(session_id)

    try:
        proc = subprocess.Popen(
            ["databricks", "bundle", "run", state_name, "-t", "dev", *(var_args or []), *_profile_args()],
            cwd=report_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        output_lines: list[str] = []
        for line in proc.stdout:
            output_lines.append(line)
            logger.debug("bundle run: %s", line.rstrip())

            if not state.run_url:
                url_match = _RUN_URL_RE.search(line)
                if url_match:
                    state.run_url = url_match.group(0)
                    rid_match = _RUN_ID_RE.search(state.run_url)
                    if rid_match:
                        state.run_id = rid_match.group(1)
                    logger.info("Captured run URL: %s (run_id=%s)", state.run_url, state.run_id)

        proc.wait(timeout=86400)

        if proc.returncode == 0:
            state.deployment = DeploymentStatus.COMPLETED
            logger.info("Bundle run completed successfully for %s", state_name)
        else:
            logger.warning(
                "Bundle run CLI exited with code %d for %s — this may be a CLI issue, "
                "not a job failure. The actual job status is polled via the Databricks API.",
                proc.returncode, state_name,
            )
            logger.debug("Last output: %s", "".join(output_lines[-20:]))
    except subprocess.TimeoutExpired:
        proc.kill()
        logger.error("Bundle run timed out after 24h for %s", state_name)
    except Exception:
        state.deployment = DeploymentStatus.FAILED
        logger.exception("Bundle run exception for %s", state_name)


@router.post("/deploy/{session_id}")
async def deploy_and_run(session_id: str, request: Request):
    """Deploy the report bundle and trigger a run (non-blocking)."""
    user_email = _get_user_email(request)
    state = _get_session_state(session_id)
    report_dir = _user_report_dir(user_email, state.name)

    if not os.path.exists(report_dir):
        raise HTTPException(400, "Report not scaffolded yet. Call /api/scaffold first.")

    state.deployment = DeploymentStatus.DEPLOYING
    env = _cli_env(user_email, user_token=request.headers.get("X-Forwarded-Access-Token"))

    notification_email = user_email or "noreply@databricks.com"

    var_args = ["--var", f"notification_email={notification_email}"]
    if state.use_all_purpose_cluster and state.all_purpose_cluster_id:
        var_args += ["--var", f"existing_cluster_id={state.all_purpose_cluster_id}"]

    try:
        subprocess.run(
            [
                "databricks", "bundle", "deploy", "-t", "dev",
                *var_args,
                *_profile_args(),
            ],
            cwd=report_dir,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        state.deployment = DeploymentStatus.FAILED
        combined = f"STDERR:\n{e.stderr}\n\nSTDOUT:\n{e.stdout}"
        raise HTTPException(500, f"Deploy failed: {combined[-3000:]}")

    state.deployment = DeploymentStatus.RUNNING
    state.deploy_started_at = time.time()
    state.user_email = user_email

    thread = threading.Thread(
        target=_background_bundle_run,
        args=(session_id, report_dir, env, state.name, var_args),
        daemon=True,
    )
    thread.start()

    return {
        "status": "running",
        "message": "Report job has been submitted. You can track the progress below.",
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
        w = _get_polling_client()
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
        w = _get_polling_client()
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
