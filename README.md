# Trazo

**Observability, replay, and governance for multi-agent AI systems.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Status](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.10%20--%203.13-blue)

Trazo records what an autonomous agent actually did — every model call, tool
invocation, memory read, and state transition — then lets you replay that exact
run step by step, detect known failure patterns in it, and block unsafe actions
before they execute.

*Trazo* is Spanish and Portuguese for a drawn stroke: the mark a pen leaves
behind. That mark, applied to an agent's execution, is what this project is
about — the durable, inspectable record of what a system did, as opposed to what
its logs claim it did.

---

## Table of contents

- [The problem](#the-problem)
- [How Trazo compares](#how-trazo-compares)
- [Core capabilities](#core-capabilities)
- [Architecture](#architecture)
- [Replay under non-determinism](#replay-under-non-determinism)
- [Requirements](#requirements)
- [Quickstart](#quickstart)
- [Instrumenting your own agent](#instrumenting-your-own-agent)
- [Replaying and verifying a run](#replaying-and-verifying-a-run)
- [Writing policies](#writing-policies)
- [Failure detection](#failure-detection)
- [Configuration reference](#configuration-reference)
- [HTTP API reference](#http-api-reference)
- [Command-line reference](#command-line-reference)
- [Repository layout](#repository-layout)
- [Development](#development)
- [Benchmarks](#benchmarks)
- [Security posture](#security-posture)
- [Deployment](#deployment)
- [Project status](#project-status)
- [Roadmap](#roadmap)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## The problem

Multi-agent LLM systems built on LangGraph, CrewAI, AutoGen, or raw MCP
tool-calling loops fail in production in ways that are hard to see and harder to
explain. An agent loops on the same tool call forty times before a timeout kills
it. A budget guard trips at 2 a.m. because a planning step spiraled into
recursive sub-tasks. A retrieval step pulls the wrong document and the agent
confidently acts on it three steps later, far from where the actual mistake
happened.

When this happens, the honest answer to "why did the agent do that" is usually
that nobody knows, and there is no way to find out short of re-reading
unstructured logs and guessing. Standard application observability was built for
systems where a request either succeeds or fails in a deterministic, mostly
linear way. Agent systems are neither. They branch on model output, hold
long-lived state across many model calls, read and write memory, and make
irreversible tool calls whose consequences are not visible in a stack trace.

This gap appears the moment a team moves an agent from "impressive demo" to
"runs unsupervised in production," and it does not close as models improve. A
more capable model still makes decisions you need to inspect, reproduce, and —
when necessary — stop before they execute.

## How Trazo compares

| | Cross-framework | Self-hostable | Step-by-step deterministic replay | Pre-execution enforcement |
|---|---|---|---|---|
| **Trazo** | Yes | Yes | Yes | Yes |
| LangSmith | LangChain/LangGraph only | No (hosted only) | No | No |
| Langfuse | Yes | Yes | View only, not re-execution | No |
| Arize Phoenix | Yes | Yes | No (evaluation-focused) | No |
| OpenTelemetry GenAI | Yes (schema layer) | Yes | Out of scope | Out of scope |

Each of these tools is good at what it targets. LangSmith is tightly integrated
with the LangChain ecosystem. Langfuse offers solid open-source tracing and
evaluation. Phoenix is strong on dataset-driven output quality. OpenTelemetry's
GenAI semantic conventions standardize what an LLM span looks like, which is
genuinely useful — Trazo's event schema stays close to them deliberately.

What none of them provide is the combination in the table above: deterministic
re-execution of one specific historical run, unified across more than one agent
framework, with policy evaluated and enforced *before* an action runs. That
combination is what Trazo is for.

## Core capabilities

**Instrumentation SDK.** A Python library that hooks into an agent framework's
execution and emits structured trace events: state transitions, tool calls and
results, memory reads and writes, inter-agent messages, planning steps, and
human-in-the-loop checkpoints. A LangGraph state transition and a CrewAI task
handoff normalize to the same event shape, so the trace format does not fork per
framework.

**Ingestion and trace store.** Events ship in batches over HTTP, flow through an
event bus (Redis Streams), and land in PostgreSQL for structured querying. Large
payloads — a 200 KB scraped page does not belong in a relational row — are
content-addressed blobs stored on the filesystem or in S3-compatible object
storage. Every event is individually addressable by `(run_id, seq)`, which is
the granularity replay depends on.

**Replay engine.** Re-drives a recorded run's control flow while substituting
every non-deterministic result from the recorded trace. See
[Replay under non-determinism](#replay-under-non-determinism).

**Failure detection.** A worker consumes the live event stream and scores runs
against known degenerate patterns: tool-call loops, budget runaways, and
tool-call thrashing. Detections are raised while the run is still executing, not
after the fact. Measured precision and recall are published in
[Benchmarks](#benchmarks). Goal drift is an opt-in, model-judged extra whose
status is stated under [Failure detection](#failure-detection).

**Policy and governance.** Guardrails evaluated by Open Policy Agent immediately
*before* a governed action executes, with a 150 ms latency budget and explicit
fail-open or fail-closed configuration. Every decision is recorded as an event
in the same trace. Enforcement is inline and synchronous, which is what makes it
a governance layer rather than an audit log.

**Dashboard.** A React interface for the run timeline, per-step flow graph,
memory inspector, replay stepper, cost and latency breakdowns by model and tool,
incident feed, and policy decision log.

## Architecture

```mermaid
flowchart TD
    subgraph user["Your process"]
        A["Agent code<br/>(LangGraph / CrewAI / custom)"]
        SDK["Trazo SDK<br/>recorder · adapters · policy hook · replay driver"]
        A -- intercepted boundaries --> SDK
    end

    SDK -- HTTP batch ingest --> CP["Control plane (FastAPI)"]
    SDK -- synchronous policy check --> CP
    CP -- evaluate --> OPA["OPA sidecar<br/>allow / deny / escalate"]
    CP -- publish --> BUS[("Event bus<br/>Redis Streams")]
    BUS --> SW["Store worker"]
    BUS --> DW["Detector worker<br/>loop · budget · thrash"]
    BUS --> LIVE["SSE fan-out"]
    SW --> PG[("PostgreSQL<br/>runs · events · detections")]
    SW --> BLOB[("Blob store<br/>filesystem / S3")]
    CP --> DASH["Dashboard (React)"]
    SDK -. replay bundle via API .-> CP
```

Two architectural decisions are worth calling out.

**Infrastructure sits behind narrow interfaces.** `EventBus`, `TraceStore`, and
`BlobStore` are protocols with the simplest working implementation chosen for
the current scope: Redis Streams rather than Kafka, PostgreSQL alone rather than
PostgreSQL plus a column store, a filesystem blob directory rather than
mandatory object storage. Heavier backends are additional implementations behind
the same seam, not rewrites.

**Policy enforcement is a synchronous SDK hook, not a bus consumer.** By the time
an asynchronous consumer observes an event, the action has already run.
Governance that only observes after the fact is reporting. The SDK therefore
calls the policy endpoint inline and raises before the governed call executes.

## Replay under non-determinism

This is the part of the system most likely to be quietly faked, so it is worth
being precise about what replay means here.

Model completions are sampled. Even at temperature zero, providers rotate weights
and deprecate versions without notice, and any tool call touching the outside
world can return something different five minutes later. Re-running the same
agent code against the same input will not, in general, reproduce the same trace.
A tool that simply runs it again is not replaying anything; it is producing a
second, uncorrelated run.

Temporal solved the adjacent problem for workflow code by recording every
non-deterministic operation's result in workflow history and satisfying each one
from that history on replay. The workflow code runs again; the outside world does
not.

Trazo applies the same idea to agent execution. Every model completion, tool
call, memory read, and external side effect during an instrumented run is
captured as a checkpointed trace event. Replay re-drives the agent's control flow
and, at each point where the original run made a non-deterministic call,
substitutes the recorded value instead of issuing a live one. You step through
exactly what the agent saw and decided at step *N* of a specific historical run.

**What this provides:** faithful, inspectable reconstruction of a specific
failure, with per-step divergence detection when replayed state does not match
what was recorded.

**What this does not provide:** prediction of what the agent would do on a fresh
run with fresh sampling. That is an evaluation problem, not a debugging one, and
is explicitly out of scope.

Replay requires an entrypoint registered in the same process, so the engine knows
which function to re-invoke for a given run — see
[Replaying and verifying a run](#replaying-and-verifying-a-run).

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Docker Desktop or Docker Engine | Compose v2 | Runs the five-service stack |
| Python | 3.10 – 3.13 | For the SDK and your agent |
| [uv](https://docs.astral.sh/uv/) | Latest | Dependency resolution; `pip install uv` |
| Node.js | 20+ | Only for dashboard development |

Host ports used by default: `8420` (control plane), `5173` (dashboard), `5432`
(PostgreSQL), `6379` (Redis), `8181` (OPA). All are configurable in
`deploy/.env`. The launcher automatically relocates the PostgreSQL and Redis host
ports if something else already holds them.

## Quickstart

### One command

Clone the repository and run the launcher. It starts Docker if needed, brings up
all five services, traces a real agent, triggers a detection, has a policy block
an action inline, and verifies replay fidelity — checking each step's actual
outcome against the control plane rather than assuming success.

```bash
git clone https://github.com/naveen-astra/Trazo.git
cd Trazo
python scripts/run_demo.py
```

On Windows you can double-click `RUN_DEMO.bat` instead. `STOP_DEMO.bat` or
`make down` tears the stack down.

Useful flags:

| Flag | Effect |
|---|---|
| `--fast` | Skip the pause between steps |
| `--keep-data` | Do not reset the database first |
| `--no-browser` | Do not open the dashboard automatically |

Expected output ends with:

```
==========================================================================
  DEMO COMPLETE -- everything verified live
==========================================================================
  Dashboard:     http://localhost:5173
  Control plane: http://localhost:8420
```

### Step by step

If you would rather run it manually:

```bash
cp deploy/.env.example deploy/.env   # sets TRAZO_API_KEY (dev-change-me by default)
make up                              # postgres, redis, opa, control-plane, dashboard
curl http://localhost:8420/readyz    # {"status":"ready","checks":{...}}
```

Trace a real instrumented LangGraph agent against the running stack:

```bash
uv run --project sdk --extra langgraph --extra demos \
    python demos/research-assistant/run.py --endpoint http://localhost:8420
```

This is a real LangGraph graph (plan, search, retrieve, synthesize, evaluate)
wrapped in `instrument()` exactly the way your own agent would be. It prints the
run id it recorded:

```
TRAZO_RUN_ID=run_01M2TAPDR1BV8E0MP4Z8N9JRCW
```

Query it back, or open the dashboard:

```bash
curl "http://localhost:8420/v1/runs?project=research-assistant"
open http://localhost:5173
```

## Instrumenting your own agent

Install the SDK from a clone (no package is published to PyPI yet):

```bash
uv pip install -e "sdk[langgraph]"     # or sdk[crewai], or plain sdk
```

### LangGraph

```python
import trazo
from trazo.integrations.langgraph import instrument

trazo.init(
    project="my-agent",
    endpoint="http://localhost:8420",
    api_key="dev-change-me",
)

graph = build_my_graph()
traced = instrument(graph)

result = traced.invoke({"query": "..."})
print(traced.last_run_id)  # the run id just recorded

trazo.shutdown()  # flush before the process exits
```

Requires LangGraph 1.2.3 or later. If a node takes the run config, type it
`RunnableConfig` (from `langchain_core.runnables`) or leave it unannotated:
LangGraph 1.x does not pass `config` to a parameter annotated as a plain
`dict`. See the adapter's
[README](sdk/src/trazo/integrations/langgraph/README.md) when upgrading
from LangGraph 0.2.

### CrewAI

```python
import trazo
from trazo.integrations.crewai import instrument

trazo.init(project="my-crew", endpoint="http://localhost:8420")

traced = instrument(my_crew)
traced.kickoff()

trazo.shutdown()
```

### Any other agent

For a hand-rolled loop or an unsupported framework, decorate the boundaries
directly. These are the same primitives the adapters use internally.

```python
from trazo import trace_tool, trace_llm, trace_memory_read, trace_memory_write


@trace_tool(side_effect_class="external")  # "read" | "write" | "external"
def web_search(query: str) -> list[str]: ...


@trace_llm(provider="openai", model="gpt-4o")
def call_model(messages: list[dict]) -> str: ...


@trace_memory_read(store="vector")
def retrieve(query: str) -> list[str]: ...


@trace_memory_write(store="vector")
def remember(fact: str) -> None: ...
```

`side_effect_class` matters for governance: by default, only `write` and
`external` calls are submitted for policy evaluation. Read-only calls are traced
but not gated, which keeps the 150 ms policy budget off your hot path.

Always call `trazo.shutdown()` before a short-lived process exits. An `atexit`
hook exists as a fallback, but it is not reliable when a process exits
immediately after the agent finishes — events still queued will be lost.

## Replaying and verifying a run

Inspect a recorded run without re-executing anything:

```python
from trazo import replay

session = replay.load("run_01M2TAPDR...", mode="strict")

for step in session.steps():
    print(step.index, step.name, step.state_before)
    # step.boundary_events holds the recorded model/tool/memory calls
    # from the original run, not freshly generated ones
```

`session.steps()` reads from the replay bundle and needs nothing else. To
actually *re-drive* the agent and measure fidelity, the engine must know which
function to re-invoke, so the run's entrypoint has to be registered in the same
process:

```python
from trazo import replay
from trazo.integrations.langgraph import instrument


@replay.entrypoint(framework="langgraph")
def run_agent(entry_input):
    return instrument(build_my_graph()).invoke(entry_input)
```

`framework=` scopes the entrypoint to bundles of that framework, so several can
coexist in one process. A bare `@replay.entrypoint` registers a default used for
any framework.

Each demo ships a small wrapper that does exactly this. With it registered,
verification reports boundary fidelity, state fidelity, and divergences:

```bash
TRAZO_API_KEY=dev-change-me uv run --project sdk --extra langgraph --extra demos \
    python demos/research-assistant/replay_entrypoint.py run_01M2TAPDR...
```

```
run run_01M2TAPDR1BV8E0MP4Z8N9JRCW (langgraph), mode=lenient (verify)
  boundary fidelity: 100.00%
  state fidelity:    100.00%
  matched: 21  reordered: 0  divergences: 0
  replay overhead:   1.51x
```

With `TRAZO_API_KEY` set, the report is persisted to the control plane and
appears in the dashboard's Replay Studio for that run.

The wrapper also re-drives like `trazo replay`: `--mode strict` stops at the
first divergence, `--mode lenient` records divergences and carries on, and
`--step N` reports only what the recording reached by the end of step `N`.
A run recorded live replays without extra settings, because the wrapper
reads the run's model labels from the recording first.

A bare `trazo verify <run_id>` will fail with `NoEntrypointRegisteredError`
unless an entrypoint was registered earlier in the same process. This is a
consequence of the design, not a bug: the engine cannot guess which callable
produced an arbitrary run.

**Modes.** `strict` fails on the first divergence; `lenient` records every
divergence and continues, which is what you want when diagnosing an unknown
failure.

## Writing policies

Policies are Rego files mounted read-only into the OPA sidecar from
`policies/trazo/`. No SDK or control-plane code changes to add one.

```rego
package trazo.decision

import rego.v1

deny contains {"policy_id": "send_email_cap", "reason": msg} if {
    input.action.tool_name == "send_email"
    input.action.projected_cost_usd > 5
    msg := "blocked: projected cost exceeds per-action budget"
}
```

The input document available to every policy:

```json
{
  "run_id": "run_01M2...",
  "action": {
    "kind": "tool.call",
    "fingerprint": "sha256:...",
    "tool_name": "web_search",
    "side_effect_class": "external",
    "projected_cost_usd": 0.1,
    "args_summary": {}
  },
  "run_context": {
    "cost_usd_so_far": 4.95,
    "active_detections": ["loop"]
  }
}
```

Rules contribute to `deny` or `escalate` sets. Any non-empty `deny` produces a
`deny` decision, which the SDK surfaces by raising `PolicyDenied` before the
governed call runs.

Enable enforcement at runtime:

```bash
TRAZO_POLICY_MODE=enforce python my_agent.py
```

OPA does not hot-reload the bundle; restart the sidecar after editing a policy:

```bash
docker compose --project-name trazo -f deploy/docker-compose.yml restart opa
```

Test policies without the stack:

```bash
docker run --rm -v "$(pwd)/policies:/policies" openpolicyagent/opa:0.70.0 \
    test /policies/trazo /policies/tests/trazo -v
```

## Failure detection

Three rule-based detectors run in a worker consuming the live event stream.
Detections are raised during execution, not in a post-hoc batch job.

| Detector | Signature | Severity |
|---|---|---|
| `loop` | The same tool called with a near-identical input fingerprint repeatedly, with no state progress | `warn` |
| `budget` | Cost velocity exceeding a configured rate cap | `critical` |
| `thrash` | Varied tool calls that keep returning the same result, with nothing new turning up | `warn` |

Each detection carries the event IDs that triggered it, so the dashboard links
straight to the evidence rather than asserting a conclusion. Measured accuracy is
in [Benchmarks](#benchmarks).

### Goal drift (opt-in, judge model required)

Goal drift — an agent wandering from what it was asked to do, or being steered
off it mid-run — is not expressible as a rule, so it is judged by a language
model instead, and it is off by default. When enabled, every second model call
a judge reads the run's stated goal and its latest four model exchanges. A
detection is raised after two consecutive off-task verdicts, at most once per
run, so one noisy answer cannot raise an alarm. A crew started without a stated
goal is judged on whether each reply answers the task in its own prompt, since
a multi-agent pipeline legitimately changes task as work moves between agents.
A judge that is unreachable, slow or unparseable counts as no verdict: drift
detection fails open and never blocks a run.

Any OpenAI-compatible endpoint can be the judge; a local Ollama costs nothing.
There is deliberately **no default model**, because the judge's accuracy is the
model's:

```bash
TRAZO_FEATURE_DRIFT_DETECTOR=true \
TRAZO_DRIFT_BASE_URL=http://host.docker.internal:11434/v1 \
TRAZO_DRIFT_MODEL=<model you have checked> \
    docker compose --project-name trazo --env-file deploy/.env \
    -f deploy/docker-compose.yml up -d control-plane
```

Score a candidate model against the labeled corpus before relying on it. The
first 8 runs of each group are the development set, so skip them:

```bash
uv run --project sdk python benchmark/detection/drift_runner.py \
    --model <model> --skip-first 8
```

**Status, stated plainly.** The detector, its wiring and its scorer are built
and tested, and the whole path (event stream, worker, judge, stored detection,
API) has been run end to end with a scripted stand-in judge. No real judge model
has passed the benchmark yet. The one tried, Qwen2.5 3B served locally, raised
drift on every run in the held-out corpus, clean runs included (100% false
positive rate, 20% precision), through three rounds of prompt changes on the
development set; its report is
[results-drift-qwen2.5-3b.md](benchmark/detection/results-drift-qwen2.5-3b.md).
A stronger model (Qwen2.5 7B is about 4.7 GB) has not been scored. The corpus's
drift runs also come from scripted agents, so a model that passes still needs
trying on your own agents.

## Configuration reference

### SDK (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `TRAZO_ENDPOINT` | `http://localhost:8420` | Control plane base URL |
| `TRAZO_API_KEY` | none | Bearer key for ingest and policy endpoints |
| `TRAZO_POLICY_MODE` | `off` | `off`, `observe` (evaluate and record, never block), `enforce` (block on deny) |
| `TRAZO_POLICY_FAIL` | `open` | Behavior when policy evaluation fails or times out: `open` allows, `closed` blocks |
| `TRAZO_POLICY_SCOPE` | `write,external` | Extra comma-separated side-effect classes to govern |
| `TRAZO_REDACT_KEYS` | built-in set | Extra comma-separated key substrings to redact, on top of `api_key`, `authorization`, `password`, and similar |
| `TRAZO_SPOOL_MAX_MB` | `256` | Disk spool cap before the oldest batches are dropped |
| `TRAZO_PRICING_FILE` | none | JSON file of `{"model-prefix": [input, output]}` USD-per-million prices, merged over the built-in table used to estimate `cost_usd` |

`observe` is the recommended way to introduce policies to an existing system:
decisions are recorded and visible in the dashboard, but nothing is blocked until
you switch to `enforce`.

### Control plane (environment variables, `TRAZO_` prefix)

| Variable | Default | Purpose |
|---|---|---|
| `TRAZO_ENVIRONMENT` | `development` | `production` requires sign-in, secure cookies and strong secrets, and hides the API docs |
| `TRAZO_API_KEY` | `dev-change-me` | Bearer key required on ingest and policy endpoints, and accepted on reads |
| `TRAZO_DASHBOARD_PASSWORD` | none | Setting it turns on dashboard sign-in; mandatory in production |
| `TRAZO_SESSION_SECRET` | none | Signs session cookies; required with a dashboard password |
| `TRAZO_SESSION_TTL_HOURS` | `12` | How long a dashboard session lasts |
| `TRAZO_LOGIN_MAX_ATTEMPTS` / `TRAZO_LOGIN_WINDOW_MINUTES` | `5` / `15` | Failed sign-ins allowed per client within the window |
| `TRAZO_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Peers trusted to set `X-Forwarded-For`; widen only behind a reverse proxy |
| `TRAZO_DATABASE_URL` | `postgresql://trazo:trazo@localhost:5432/trazo` | PostgreSQL connection string |
| `TRAZO_REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `TRAZO_OPA_URL` | `http://localhost:8181` | OPA sidecar base URL |
| `TRAZO_BLOB_ROOT` | `/var/lib/trazo/blobs` | Filesystem blob store root |
| `TRAZO_HOST` / `TRAZO_PORT` | `0.0.0.0` / `8420` | Bind address |
| `TRAZO_STALE_RUN_TTL_HOURS` | `6` | A `running` run older than this is marked `stale` |
| `TRAZO_CORS_ORIGINS` | `*` | Browser origins allowed to read query endpoints |
| `TRAZO_LOG_JSON` | `true` | JSON logs in containers, human-readable when `false` |
| `TRAZO_FEATURE_STORE_WORKER` | `true` | Run the persistence worker in-process |
| `TRAZO_FEATURE_DETECTOR_WORKER` | `true` | Run the detection worker in-process |
| `TRAZO_FEATURE_DRIFT_DETECTOR` | `false` | Judge goal drift with a model (needs `TRAZO_DRIFT_MODEL`) |
| `TRAZO_DRIFT_MODEL` | none | Judge model name; required when drift detection is on |
| `TRAZO_DRIFT_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible judge endpoint (from a container, the host's Ollama is `http://host.docker.internal:11434/v1`) |
| `TRAZO_DRIFT_API_KEY` | none | Bearer key for the judge endpoint, if it needs one |
| `TRAZO_DRIFT_EVERY_N_LLM_CALLS` / `TRAZO_DRIFT_CONFIRMATIONS` | `2` / `2` | Judge every Nth model call; consecutive off-task verdicts needed to raise a detection |
| `TRAZO_DRIFT_TIMEOUT_SECONDS` | `30` | Per-judgment time limit |

In production, the control plane refuses to start if the API key, dashboard
password, session secret, or database password is missing, too short, or a
development default, or if `TRAZO_CORS_ORIGINS` is `*`. It lists every problem
at once.

### Deployment ports (`deploy/.env`)

`POSTGRES_PORT`, `REDIS_PORT`, `OPA_PORT`, `CONTROL_PLANE_PORT`,
`DASHBOARD_PORT`, plus `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`.
Copy `deploy/.env.example` to `deploy/.env` to start. Production uses
`deploy/.env.production` instead, generated with random secrets — see
[Deployment](#deployment).

## HTTP API reference

Base URL `http://localhost:8420` locally, or your domain in production.
Endpoints marked **key** require `Authorization: Bearer $TRAZO_API_KEY`.

When sign-in is enabled (always, in production), every query and live-stream
endpoint also requires authentication: either a dashboard session cookie or the
API key as a bearer token. A session grants read access only.

### Authentication

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/auth/session` | Whether sign-in is required, and whether this client is signed in |
| `POST` | `/v1/auth/login` | Sign in with `{"password": "..."}`; sets the session cookie |
| `POST` | `/v1/auth/logout` | End the session |

### Ingest and policy

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/v1/ingest/events` | key | Batch event ingest |
| `POST` | `/v1/ingest/blobs` | key | Content-addressed large payload upload |
| `POST` | `/v1/policy/evaluate` | key | Synchronous policy decision for one action |

### Query

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/runs` | List runs; filters `project`, `status`, `limit`, `cursor` |
| `GET` | `/v1/runs/{run_id}` | One run and its rollup totals |
| `GET` | `/v1/runs/{run_id}/events` | Events in `seq` order; filters `kind`, `after_seq`, `limit` |
| `GET` | `/v1/runs/{run_id}/detections` | Detections raised on this run |
| `GET` | `/v1/runs/{run_id}/policy-decisions` | Policy decisions recorded on this run |
| `GET` | `/v1/runs/{run_id}/replay-bundle` | Everything needed to replay this run |
| `GET` / `POST` | `/v1/runs/{run_id}/replay-report` | Fetch or submit a fidelity report |
| `GET` | `/v1/projects` | Known projects with run counts |
| `GET` | `/v1/stats` | Dashboard aggregates: success rate, cost, percentiles |
| `GET` | `/v1/tools` | Per-tool call counts, errors, p50/p95 latency |
| `GET` | `/v1/agents` | Per-agent event and run counts |
| `GET` | `/v1/models` | Per-model cost, tokens, latency percentiles |
| `GET` | `/v1/detections` | Cross-run detection feed; filters `project`, `detector`, `severity` |
| `GET` | `/v1/policy-decisions` | Cross-run decision feed; filters `project`, `decision`, `policy_id` |
| `GET` | `/v1/events/recent` | Recent events across runs |
| `GET` | `/v1/blobs/{sha256}` | Fetch an offloaded payload |

### Live streams and operations

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/live/firehose` | Server-Sent Events across all runs; `Last-Event-ID` resume |
| `GET` | `/v1/live/runs/{run_id}` | Server-Sent Events for one run |
| `GET` | `/healthz` | Liveness and version |
| `GET` | `/readyz` | Readiness with per-dependency checks |
| `GET` | `/metrics` | Prometheus metrics (not served publicly in production) |

An OpenAPI schema is served at `/openapi.json` and browsable at `/docs` in
development. Production turns both off.

## Command-line reference

The SDK installs a `trazo` executable. A global `--endpoint` must precede the
subcommand.

| Command | Purpose |
|---|---|
| `trazo doctor` | Check connectivity, spool status, and version skew |
| `trazo tail <run_id>` | Stream one run's events live |
| `trazo replay <run_id> [--step N] [--mode strict\|lenient] [--json]` | Re-drive a recorded run under a registered entrypoint |
| `trazo verify <run_id> [--json] [--no-submit]` | Fidelity report: boundary, state, overhead |

```bash
trazo --endpoint http://localhost:8420 doctor
trazo --endpoint http://localhost:8420 tail run_01M2TAPDR...
```

`replay` and `verify` require a registered entrypoint in the same process — see
[Replaying and verifying a run](#replaying-and-verifying-a-run).

## Repository layout

```
sdk/                     Python SDK: recorder, adapters, policy hook, replay engine, CLI
control-plane/           FastAPI service: ingest, query, policy, SSE, workers, migrations
dashboard/               React + TypeScript + Vite frontend
policies/                Rego policy bundle and its tests
deploy/                  Docker Compose stack, Dockerfiles, environment template
demos/                   Runnable example agents (LangGraph and CrewAI)
benchmark/               TrazoBench: corpus, scoring runners, adapter interface, results
schema/                  Frozen trace event JSON Schema and fixtures
scripts/                 Launcher, smoke checkpoints, developer utilities
```

Each directory has its own `README.md` with specifics.

## Development

```bash
make up            # start the stack
make down          # stop it
make nuke          # stop it and drop volumes
make test          # SDK and control-plane test suites
make lint          # ruff, mypy, eslint, prettier
make fmt           # auto-format
make benchmark     # regenerate benchmark tables from the committed corpus
make demo          # bring the stack up and trace one run
make gen-api-types # regenerate dashboard types from the OpenAPI schema
```

Per-package commands:

```bash
cd sdk           && uv run pytest && uv run mypy
cd control-plane && uv run pytest && uv run mypy --strict src
cd dashboard     && npm run lint && npm run build
```

The control-plane suite includes PostgreSQL integration tests that skip
automatically when a database is not reachable. Run `make up` first to execute
them — see [Troubleshooting](#troubleshooting) if they skip unexpectedly.

The trace event schema is frozen at `schema-v1.0`. CI fails any pull request that
modifies `schema/trace-event.v1.schema.json` without a version bump.

## Benchmarks

TrazoBench scores detection accuracy and replay fidelity against a labeled
corpus of injected failures. All numbers regenerate from committed manifests
with `make benchmark` — they are computed, not transcribed.

**Detection accuracy** (50 faulty runs per class, 100 clean runs):

| Class | Precision | Recall | False positive rate (clean) |
|---|---|---|---|
| loop | 67% | 100% | 0% |
| budget | 100% | 100% | 0% |
| thrash | 100% | 50% | 0% |

**Baseline comparison**, flag-any-fault, against a random flagger:

| Adapter | Precision | Recall | False positive rate |
|---|---|---|---|
| Trazo (loop + budget + thrash) | 100% | 62% | 0% |
| Random flagger baseline | 71% | 82% | 67% |

**Replay fidelity** across the demo corpus: 100% boundary fidelity, 100% state
fidelity, 0 divergences, with replay overhead between 1.5x and 5x depending on
machine and cache state.

These numbers are reported as measured, including where they are weak. The
`thrash` detector used to fire on every long research-assistant run, budget and
drift runs included, which was a 33% precision. It now also requires the recent
calls to have returned the same result, so an agent that revisits queries but
learns from each one is left alone. That raised thrash precision to 100% and
lowered the flag-any-fault recall from 75% to 62%: the 25 drift runs had only
looked detected because thrash fired on them by mistake, and no rule detector
targets drift. Thrash recall stays at 50% because the content-pipeline corpus
runs make five tool calls, fewer than the six-call window.
A third-party tool can be scored against the same corpus by implementing the
adapter interface in `benchmark/adapter.py`. Details in
[benchmark/README.md](benchmark/README.md).

## Security posture

Trazo runs in one of two modes, chosen by `TRAZO_ENVIRONMENT`.

**Development** (the default, `deploy/docker-compose.yml`) is built for one
engineer on localhost. The dashboard and read API are open, every service port
is published, and credentials are development defaults. Never expose it to a
network you do not control.

**Production** (`deploy/docker-compose.prod.yml`) is built for the public
internet:

- **HTTPS only.** Caddy terminates TLS with an automatically issued and renewed
  certificate, redirects HTTP, and sets HSTS, a strict Content-Security-Policy,
  and frame, referrer, and permissions policies.
- **Sign-in required.** Reading any run data needs either a dashboard session or
  the API key. Sessions are `HttpOnly`, `Secure`, `SameSite=Strict`, `__Host-`
  prefixed cookies that expire after 12 hours by default. Five failed sign-ins
  from one client in fifteen minutes locks that client out for the window.
- **Writes stay key-only.** Sending events and evaluating policy always require
  the API key. A browser session can read but never write.
- **Minimal exposure.** Only the reverse proxy publishes a port. PostgreSQL,
  Redis, and OPA are on an internal network with no route to the internet, and
  Redis is password-protected. API docs and `/metrics` are not served publicly.
- **Hardened containers.** The control plane runs as an unprivileged user.
  Containers drop all Linux capabilities they do not need, run with
  `no-new-privileges`, and have memory limits and log rotation.
- **Refuses weak configuration.** The control plane will not start in production
  with a missing, short, or default secret, and names every problem at once.

In both modes, every recorded event passes through a redaction pass
(configurable key patterns) before it leaves your process, API keys are compared
in constant time, large payloads are stored content-addressed by SHA-256, and
OPA policies are code-reviewed files mounted read-only, with no runtime upload
endpoint.

**Not multi-tenant.** Production has one shared dashboard password, not user
accounts: no per-user audit trail, no roles, no SSO. Share it only with people
who should see every run. `project_id` is threaded through every table so
per-user access is additive later rather than a schema migration.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Deployment

A production deployment is one Linux server, a domain, and about twenty
minutes. The complete runbook — DNS, firewall, verification, backups, restore,
updates, and credential rotation — is in [deploy/README.md](deploy/README.md).
The short version:

```bash
git clone https://github.com/naveen-astra/Trazo.git /opt/trazo && cd /opt/trazo
make prod-init DOMAIN=trazo.example.com EMAIL=ops@example.com   # generates every secret
make prod-up                                                    # builds, starts, issues the certificate
```

`prod-init` writes `deploy/.env.production` with random credentials and prints
the dashboard password and API key once. Point agents at the deployment with:

```bash
export TRAZO_ENDPOINT=https://trazo.example.com
export TRAZO_API_KEY=<the API key>
```

Back up with `make prod-backup`, which writes a PostgreSQL dump and a blob-store
archive and prunes old backups; schedule it from cron. Database migrations run
automatically on every start.

## Project status

Version 0.1.0. All seven development phases are code-complete, with passing test
suites, working end to end against a live stack.

| Component | Status |
|---|---|
| Trace event schema | Frozen at `schema-v1.0`; CI enforces version bumps |
| Python SDK | Complete |
| LangGraph adapter | Complete |
| CrewAI adapter | Complete: tracing, plus inline policy enforcement on the crew's agent and task tools |
| Ingestion pipeline | Complete: HTTP to Redis Streams to PostgreSQL |
| Replay engine | Complete: record-and-substitute, divergence detection, fidelity harness |
| Failure detection | Complete: three rule-based detectors, scored against a 300-run labeled corpus. Goal drift: opt-in judge built and tested, no judge model validated yet |
| Policy engine | Complete: synchronous inline enforcement via OPA |
| Dashboard | Complete: timeline, flow graph, memory inspector, replay stepper, incidents, policy log, settings |
| TrazoBench | Complete: adapter interface, corpus manifests, baseline comparison |
| Production deployment | Complete: HTTPS, sign-in, internal-only datastores, hardened containers, backups |
| Published packages | Not yet on PyPI or npm — install from a clone |

Known limitations, stated explicitly:

- Inline policy enforcement covers LangGraph, CrewAI and decorator-instrumented
  code. CrewAI's event bus is fire-and-forget, so the CrewAI adapter instead
  wraps each tool on the crew's agents and tasks for the length of `kickoff()`.
  CrewAI catches tool exceptions and shows them to the agent, so the crew keeps
  going after a denial; the denied tool never runs, and `kickoff()` raises
  `PolicyDenied` once the crew stops. Tools added to an agent mid-run are not
  governed.
- The `thrash` detector catches only half of the injected thrash runs (50%
  recall): runs shorter than its six-call window are never judged. It flags a
  run when varied calls keep returning the identical result, so a tool that
  fails differently each time, or an agent that thrashes through a tool whose
  results vary, is not caught.
- Goal-drift detection is built but unproven: it needs a judge model, and the
  one tried (Qwen2.5 3B) flagged every run, so no model is recommended yet.
  While it runs it waits on the judge, so a slow judge delays other detectors on
  the same worker.
- The demo agents use deterministic scripted model responses by default so the
  demo costs nothing and reproduces exactly. Pass `--live` for real model
  calls: against OpenAI with an API key, or free against a local model served by
  Ollama (verified with Qwen2.5 3B; see `demos/_shared/README.md`). Everything
  else in the pipeline is real infrastructure.

## Roadmap

Ordered by dependency rather than calendar, and gated on demand rather than
speculation.

1. **AutoGen adapter** — third framework; tests the generality of the adapter
   contract.
2. **Replay forking** — mutate one recorded boundary result and continue live
   from that point. The bundle format already supports it.
3. **TypeScript SDK** — after the Python adapter contract survives three
   frameworks unchanged.
4. **Kafka event bus** — when measured ingest exceeds what a single Redis stream
   handles comfortably. The interface already exists.
5. **Column-store analytics** — when dashboard aggregates outgrow PostgreSQL.
   The `TraceStore` seam already exists.
6. **OpenTelemetry exporter** — map events to GenAI-semconv spans so Trazo data
   is visible in existing Grafana and Jaeger installations.
7. **Authentication and authorization** — per-project API keys, then SSO, then
   RBAC. `project_id` is already on every row.
8. **Auto-pause escalation** — a policy `escalate` decision suspends the run
   pending human approval. Requires framework-side pause hooks per adapter.

Explicit non-goals: an evaluation and quality-scoring platform, prompt
management, an agent-building framework, and prediction of fresh-run outcomes.

## Troubleshooting

**The launcher cannot reach Docker.** Start Docker Desktop and wait for the whale
icon to settle, then re-run. On Linux, `sudo systemctl start docker`.

**A port is already in use.** The launcher relocates PostgreSQL and Redis
automatically. For the control plane (`8420`) or dashboard (`5173`) it stops
instead, because those URLs are what the documentation tells you to open — change
`CONTROL_PLANE_PORT` or `DASHBOARD_PORT` in `deploy/.env`.

**PostgreSQL integration tests skip even though the stack is up.** Something else
on the host is bound to port 5432 — commonly a natively installed PostgreSQL
service — and is answering instead of the container. Docker may still report
success because it bound a different interface. Change `POSTGRES_PORT` in
`deploy/.env` and point `TRAZO_DATABASE_URL` at the new port.

**`NoEntrypointRegisteredError` when replaying.** `replay` and `verify` need
`@replay.entrypoint` registered in the same process. Use a wrapper like
`demos/research-assistant/replay_entrypoint.py`.

**Policy changes have no effect.** OPA does not watch the bundle directory.
Restart the sidecar: `docker compose --project-name trazo -f
deploy/docker-compose.yml restart opa`.

**Events are missing from a short-lived script.** Call `trazo.shutdown()` before
the process exits. The `atexit` fallback is not reliable when a process exits
immediately after the agent finishes.

**A run stays `running` forever.** The process died before emitting
`run.finished`. The store worker marks such runs `stale` after
`TRAZO_STALE_RUN_TTL_HOURS` (default 6).

**`trazo: unrecognized arguments`.** The global `--endpoint` flag must come
before the subcommand: `trazo --endpoint URL verify RUN_ID`.

## Contributing

Issues and pull requests are welcome. Before sending a large change, open an
issue to align on the approach — for a project at this stage, agreeing on design
saves more time than it costs.

Every pull request must pass `make lint` and `make test`. New behavior needs a
test that fails without the change; bug fixes need a regression test verified to
fail against the unfixed code. Changes to `schema/trace-event.v1.schema.json`
require a schema version bump, which CI enforces.

Issue and pull request templates live in [.github/](.github/).

## License

MIT. See [LICENSE](LICENSE).
