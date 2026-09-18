#!/usr/bin/env python3
"""One-command Trazo demo: brings the whole stack up and drives the full
MASTER_PLAN.md 4.3 / DEMO_RUNBOOK.md six-step demo end to end, checking
each step's outcome instead of just running commands and hoping.

    python scripts/run_demo.py              # full demo, pauses between steps
    python scripts/run_demo.py --fast       # same, no pauses (CI / re-runs)
    python scripts/run_demo.py --keep-data  # don't reset the database first

Windows users can double-click RUN_DEMO.bat instead, which just calls
this. Stdlib only, so it runs under any Python 3.10+ with no install
step -- the demo agents themselves run through `uv`, which resolves
their dependencies on first use.

Every step verifies itself against the live control plane's own query
API (not the script's assumptions about what it just did), so a green
run here means the pipeline genuinely worked, not that five commands
exited zero.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose.yml"
ENV_FILE = REPO_ROOT / "deploy" / ".env"
PROJECT_NAME = "trazo"

CONTROL_PLANE = "http://localhost:8420"
DASHBOARD = "http://localhost:5173"

COMPOSE = [
    "docker",
    "compose",
    "--project-name",
    PROJECT_NAME,
    "--env-file",
    str(ENV_FILE),
    "-f",
    str(COMPOSE_FILE),
]

# The demo agent runs through uv so its extras resolve without a manual
# install step; these are the two extras demos/research-assistant needs.
UV_RUN = [
    "uv",
    "run",
    "--project",
    "sdk",
    "--extra",
    "langgraph",
    "--extra",
    "demos",
    "python",
]


class DemoFailed(Exception):
    """A step's outcome didn't match what the demo claims it proves."""


# --------------------------------------------------------------------------
# console helpers (ASCII only -- a Windows console in cp1252 mangles box art)
# --------------------------------------------------------------------------


def banner(text: str) -> None:
    print()
    print("=" * 74)
    print(f"  {text}")
    print("=" * 74)


def step(number: int, total: int, text: str) -> None:
    print()
    print("-" * 74)
    print(f"  STEP {number}/{total}  {text}")
    print("-" * 74)


def info(text: str) -> None:
    print(f"    {text}")


def ok(text: str) -> None:
    print(f"    [OK] {text}")


def fail(text: str) -> None:
    print(f"    [!!] {text}")


def pause(enabled: bool, text: str = "Press Enter to continue...") -> None:
    if not enabled:
        return
    try:
        input(f"\n    >> {text}")
    except EOFError:  # piped stdin (CI): behave like --fast
        pass


# --------------------------------------------------------------------------
# process + HTTP helpers
# --------------------------------------------------------------------------


def run(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    quiet: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a command from the repo root, capturing output as text."""
    merged = {**os.environ, **(env or {})}
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=merged,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not quiet:
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr)
    if check and proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-15:]
        raise DemoFailed(
            f"command failed ({proc.returncode}): {' '.join(cmd[:4])}...\n"
            + "\n".join(f"      {line}" for line in tail)
        )
    return proc


def get_json(path: str, timeout: float = 10.0) -> object:
    with urllib.request.urlopen(f"{CONTROL_PLANE}{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for_ready(timeout_seconds: int = 180) -> None:
    """Poll /readyz until the control plane reports Postgres AND Redis ok."""
    deadline = time.time() + timeout_seconds
    last = ""
    while time.time() < deadline:
        try:
            payload = get_json("/readyz", timeout=5.0)
            if isinstance(payload, dict) and payload.get("status") == "ready":
                checks = payload.get("checks", {})
                ok(f"control plane ready (postgres={checks.get('postgres')}, redis={checks.get('redis')})")
                return
            last = str(payload)
        except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError) as exc:
            last = str(exc)
        time.sleep(2)
    raise DemoFailed(f"control plane never became ready within {timeout_seconds}s (last: {last})")


def extract_run_id(text: str) -> str:
    match = re.search(r"TRAZO_RUN_ID=(\S+)", text)
    if match is None:
        raise DemoFailed("the demo agent never printed a TRAZO_RUN_ID")
    return match.group(1)


# --------------------------------------------------------------------------
# demo steps
# --------------------------------------------------------------------------


def ensure_docker(timeout_seconds: int = 240) -> None:
    """Make sure the Docker daemon answers, starting Docker Desktop if this
    is Windows/macOS and it simply isn't running yet."""
    if shutil.which("docker") is None:
        raise DemoFailed("docker is not installed or not on PATH -- install Docker Desktop first")

    if subprocess.run(["docker", "info"], capture_output=True).returncode == 0:
        ok("docker daemon is running")
        return

    info("docker daemon isn't responding; trying to start Docker Desktop...")
    if sys.platform == "win32":
        desktop = Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe")
        if desktop.exists():
            subprocess.Popen([str(desktop)])
        else:
            raise DemoFailed(f"Docker Desktop not found at {desktop} -- start Docker manually, then re-run")
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-a", "Docker"])
    else:
        raise DemoFailed("docker daemon isn't running -- start it (e.g. `sudo systemctl start docker`), then re-run")

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if subprocess.run(["docker", "info"], capture_output=True).returncode == 0:
            ok("docker daemon is running")
            return
        time.sleep(4)
    raise DemoFailed(f"docker daemon didn't come up within {timeout_seconds}s")


def ensure_env_file() -> None:
    """A fresh clone has deploy/.env.example but no deploy/.env; create it
    rather than making the first-time user read an error to learn that."""
    if ENV_FILE.exists():
        return
    example = ENV_FILE.with_name(".env.example")
    if not example.exists():
        raise DemoFailed(f"neither {ENV_FILE} nor {example} exists -- cannot configure the stack")
    shutil.copyfile(example, ENV_FILE)
    ok(f"created {ENV_FILE.relative_to(REPO_ROOT)} from .env.example (dev defaults)")


def _remap_busy_host_port(compose_output: str) -> str | None:
    """Compose refuses to start when a host port is taken by something else
    on the machine -- very common for 5432/6379, which half the world's dev
    containers also bind. Only postgres and redis get remapped: the services
    inside the compose network still reach each other on their own ports, so
    the host binding is purely for optional local tooling. The control plane
    and dashboard ports are deliberately NOT remapped -- their URLs are what
    the demo tells you to open, so a silent move would be worse than an error.
    """
    match = re.search(r"Bind for [\d.:]*?:(\d+) failed: port is already allocated", compose_output)
    if match is None:
        return None
    busy = int(match.group(1))

    remappable = {"POSTGRES_PORT", "REDIS_PORT"}
    text = ENV_FILE.read_text(encoding="utf-8")
    for var in remappable:
        current = re.search(rf"^{var}=(\d+)$", text, re.MULTILINE)
        if current is None or int(current.group(1)) != busy:
            continue
        for candidate in range(busy + 1, busy + 40):
            if _port_is_free(candidate):
                ENV_FILE.write_text(
                    re.sub(rf"^{var}=\d+$", f"{var}={candidate}", text, flags=re.MULTILINE),
                    encoding="utf-8",
                )
                info(f"host port {busy} is taken by another program; moved {var} to {candidate}")
                info("(internal only -- the services still talk to each other over the compose network)")
                return var
    return None


def _port_is_free(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _preflight_host_ports() -> None:
    """Move postgres/redis off any host port something else already holds.

    Doing this *before* compose rather than only reacting to its failure
    matters because the bad case is silent: a native Postgres bound to
    0.0.0.0:5432 leaves Docker able to bind :: only, so compose reports
    success while every localhost connection reaches the wrong server.
    That shape cost real debugging time -- it makes this repo's Postgres
    integration tests skip themselves, which is how a foreign-key bug in
    the policy endpoint reached a live demo uncaught.
    """
    text = ENV_FILE.read_text(encoding="utf-8")
    changed = False
    for var in ("POSTGRES_PORT", "REDIS_PORT"):
        match = re.search(rf"^{var}=(\d+)$", text, re.MULTILINE)
        if match is None or _port_is_free(int(match.group(1))):
            continue
        busy = int(match.group(1))
        for candidate in range(busy + 1, busy + 40):
            if _port_is_free(candidate):
                text = re.sub(rf"^{var}=\d+$", f"{var}={candidate}", text, flags=re.MULTILINE)
                info(f"host port {busy} is already in use; using {candidate} for {var}")
                changed = True
                break
    if changed:
        ENV_FILE.write_text(text, encoding="utf-8")
        info("(internal only -- the services still reach each other over the compose network)")


def bring_stack_up(reset_data: bool) -> None:
    ensure_env_file()
    _preflight_host_ports()
    if reset_data:
        info("resetting any previous demo data (docker compose down --volumes)...")
        run([*COMPOSE, "down", "--volumes", "--remove-orphans"], check=False)
    info("building and starting postgres, redis, opa, control-plane, dashboard...")
    info("(first run pulls images and builds -- this can take a few minutes)")

    proc = run([*COMPOSE, "up", "-d", "--build"], check=False)
    if proc.returncode != 0:
        combined = proc.stdout + proc.stderr
        if _remap_busy_host_port(combined) is not None:
            info("retrying with the adjusted port...")
            run([*COMPOSE, "up", "-d", "--build"])
        else:
            tail = combined.strip().splitlines()[-15:]
            raise DemoFailed(
                "docker compose could not start the stack:\n"
                + "\n".join(f"      {line}" for line in tail)
            )
    ok("compose stack started")
    wait_for_ready()

    health = get_json("/healthz")
    if isinstance(health, dict):
        ok(f"control plane version {health.get('version')} reporting healthy")


def step_trace_a_real_run(pauses: bool) -> str:
    info("running a real LangGraph agent (plan -> search -> retrieve -> synthesize),")
    info("instrumented with trazo.integrations.langgraph.instrument()...")
    proc = run([*UV_RUN, "demos/research-assistant/run.py", "--endpoint", CONTROL_PLANE])
    run_id = extract_run_id(proc.stdout + proc.stderr)
    ok(f"agent finished, run_id = {run_id}")

    # Verify against the control plane's own store, not the agent's word for it.
    deadline = time.time() + 60
    rollup: dict[str, object] = {}
    while time.time() < deadline:
        try:
            candidate = get_json(f"/v1/runs/{run_id}")
            if isinstance(candidate, dict) and candidate.get("status") not in (None, "running"):
                rollup = candidate
                break
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass
        time.sleep(2)
    if not rollup:
        raise DemoFailed(f"run {run_id} never reached a terminal status in the store")

    totals = rollup.get("totals", {})
    if not isinstance(totals, dict):
        raise DemoFailed(f"run {run_id} has no totals rollup")
    ok(
        f"persisted via Redis Streams -> Postgres: {totals.get('events')} events, "
        f"{totals.get('llm_calls')} llm calls, {totals.get('tool_calls')} tool calls, "
        f"status={rollup.get('status')}"
    )
    info(f"watch it live at {DASHBOARD}/runs/{run_id}")
    pause(pauses, "Open the run in the dashboard, then press Enter for the next step...")
    return run_id


def step_detection_fires(pauses: bool) -> None:
    info("injecting a tool-call loop into a fresh run -- the same query every")
    info("iteration, so web_search fires with an identical fingerprint...")
    proc = run(
        [
            *UV_RUN,
            "demos/research-assistant/chaos_run.py",
            "loop",
            "--endpoint",
            CONTROL_PLANE,
        ]
    )
    run_id = extract_run_id(proc.stdout + proc.stderr)
    ok(f"chaos run finished, run_id = {run_id}")

    info("waiting for the live DetectorWorker to score it off the event bus...")
    deadline = time.time() + 60
    detections: list[object] = []
    while time.time() < deadline:
        try:
            payload = get_json(f"/v1/runs/{run_id}/detections")
            if isinstance(payload, dict):
                found = payload.get("detections")
                if isinstance(found, list) and found:
                    detections = found
                    break
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass
        time.sleep(2)

    if not detections:
        raise DemoFailed(f"the loop detector never fired on run {run_id}")

    detectors = sorted({d.get("detector") for d in detections if isinstance(d, dict)})
    ok(f"{len(detections)} detection(s) raised by: {', '.join(str(d) for d in detectors)}")
    info(f"see the evidence at {DASHBOARD}/runs/{run_id}")
    pause(pauses, "Look at the detection in the dashboard, then press Enter...")


def step_policy_blocks(pauses: bool) -> None:
    info("turning policy enforcement ON and injecting a budget runaway --")
    info("OPA should deny the over-budget tool call BEFORE it executes...")
    proc = run(
        [
            *UV_RUN,
            "demos/research-assistant/chaos_run.py",
            "budget",
            "--endpoint",
            CONTROL_PLANE,
        ],
        env={"TRAZO_POLICY_MODE": "enforce"},
        check=False,  # PolicyDenied propagating IS the success case here
    )
    combined = proc.stdout + proc.stderr

    if "PolicyDenied" not in combined:
        raise DemoFailed(
            "expected the run to be stopped by a PolicyDenied, but it wasn't -- "
            "the policy did not block the call"
        )

    reason = ""
    for line in combined.splitlines():
        if "PolicyDenied" in line and "cost_cap" in line:
            reason = line.strip()
            break
    ok("the SDK raised PolicyDenied -- the call never executed")
    if reason:
        info(reason)

    # A raw Go fmt escape here would mean the cost_cap policy regressed.
    if "%!f" in combined or "%!d" in combined:
        raise DemoFailed("the denial message leaked a raw Go format artifact (cost_cap regression)")

    info(f"the deny decision is recorded on the run at {DASHBOARD}/policy")
    pause(pauses, "Check the Policy page in the dashboard, then press Enter...")


def step_replay_verifies(run_id: str, pauses: bool) -> None:
    info(f"replaying the clean run ({run_id}) with recorded boundaries")
    info("substituted back in, and comparing state hashes step by step...")
    proc = run(
        [
            *UV_RUN,
            "demos/research-assistant/replay_entrypoint.py",
            run_id,
        ],
        env={"TRAZO_API_KEY": os.environ.get("TRAZO_API_KEY", "dev-change-me")},
    )
    combined = proc.stdout + proc.stderr

    for line in combined.splitlines():
        if any(k in line for k in ("fidelity", "matched:", "overhead")):
            info(line.strip())

    divergences = re.search(r"divergences:\s*(\d+)", combined)
    if divergences is None:
        raise DemoFailed("replay produced no divergence count -- verification did not run")
    if divergences.group(1) != "0":
        raise DemoFailed(f"replay found {divergences.group(1)} divergence(s) -- fidelity is not clean")

    if "100.00%" not in combined:
        raise DemoFailed("replay did not report 100% fidelity")

    ok("replay reproduced the run exactly: 100% fidelity, 0 divergences")
    info(f"step through it visually at {DASHBOARD}/runs/{run_id}/replay")
    pause(pauses, "Open the replay stepper, then press Enter for the summary...")


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the complete Trazo stack and the full six-step demo."
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="don't pause between steps (for re-runs and unattended use)",
    )
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="keep any existing demo data instead of resetting the database first",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="don't open the dashboard in a browser",
    )
    args = parser.parse_args()
    pauses = not args.fast

    banner("TRAZO -- full stack + live demo")
    print("  Everything below runs for real: a real agent, traced over HTTP into a")
    print("  real Redis stream, persisted to real Postgres, scored by a real detector")
    print("  worker, governed by a real OPA policy engine, and replayed for real.")
    print("  Nothing here is mocked or pre-recorded.")

    total = 5
    try:
        step(1, total, "Bring the stack up")
        ensure_docker()
        bring_stack_up(reset_data=not args.keep_data)

        if not args.no_browser:
            info(f"opening the dashboard at {DASHBOARD} ...")
            webbrowser.open(DASHBOARD)
        pause(pauses, "Dashboard open? Press Enter to trace the first run...")

        step(2, total, "Trace a real agent run into the dashboard")
        clean_run_id = step_trace_a_real_run(pauses)

        step(3, total, "Inject a tool-call loop; watch the detector fire")
        step_detection_fires(pauses)

        step(4, total, "A cost-cap policy blocks an over-budget call inline")
        step_policy_blocks(pauses)

        step(5, total, "Replay the clean run and verify state fidelity")
        step_replay_verifies(clean_run_id, pauses)

    except DemoFailed as exc:
        banner("DEMO FAILED")
        fail(str(exc))
        print()
        print("  The stack is still running, so you can investigate:")
        print(f"    docker compose --project-name {PROJECT_NAME} -f deploy/docker-compose.yml logs control-plane")
        return 1
    except KeyboardInterrupt:
        print("\n\n  Interrupted. The stack is still running -- stop it with STOP_DEMO.bat")
        return 130

    banner("DEMO COMPLETE -- everything verified live")
    print(f"  Dashboard:     {DASHBOARD}")
    print(f"  Control plane: {CONTROL_PLANE}")
    print(f"  Clean run:     {DASHBOARD}/runs/{clean_run_id}")
    print()
    print("  What just got proven, end to end:")
    print("    - a real LangGraph agent traced into Postgres through Redis Streams")
    print("    - the loop detector scoring a live run off the event bus")
    print("    - OPA denying an over-budget tool call before it executed")
    print("    - replay reproducing the run at 100% state fidelity, 0 divergences")
    print()
    print("  The stack stays up so you can explore. Stop it with STOP_DEMO.bat")
    print("  (or: docker compose --project-name trazo -f deploy/docker-compose.yml down)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
