package trazo.decision

import rego.v1

# Entrypoint the control plane queries: `POST /v1/data/trazo/decision`
# (API_SPEC.md "Policy", ADR-006). `opa run --server /policies`
# (deploy/docker-compose.yml) loads every .rego file under policies/
# regardless of its path — only the `package` declaration matters for
# routing — and this file's rules are exactly what that response body
# is: `{"decision": ..., "policy_id": ..., "reasons": [...]}`, echoed by
# the control plane verbatim (it adds `eval_ms` itself, timed around the
# HTTP call).
#
# Starter policies (cost_cap.rego, tool_blocklist.rego,
# active_detection.rego, TRZ-P6-02) each contribute to `deny`/`escalate`
# — sets of `{"policy_id", "reason"}` objects — rather than defining
# `decision` themselves: a second file also assigning `decision` would
# conflict the moment both bodies matched the same input. Combining
# through a set means adding a new policy can never create that
# conflict, only add another element.

# None of the three starter policies (TRZ-P6-02) escalate rather than
# deny outright, so nothing else in this bundle currently contributes to
# `escalate` -- declared here as an always-empty placeholder so
# `count(escalate)`/`with escalate as ...` compile regardless of which
# policy files are loaded, and so a future policy (e.g. a "maybe" verdict
# from TRZ-P5-07's drift classifier) has an existing rule to extend via
# its own `escalate contains {...} if {...}` in another file.
escalate contains reason if {
	false
	reason := ""
}

default _firing := set()

_firing := deny if count(deny) > 0

_firing := escalate if {
	count(deny) == 0
	count(escalate) > 0
}

default decision := "allow"

decision := "deny" if count(deny) > 0

decision := "escalate" if {
	count(deny) == 0
	count(escalate) > 0
}

default policy_id := ""

# Deduplicated: one policy can contribute more than one deny reason (a
# `sort([r.policy_id | some r in _firing])` list comprehension would
# repeat "cost_cap" once per matching rule instead of once per policy).
policy_id := concat(",", sort({r.policy_id | some r in _firing})) if count(_firing) > 0

reasons := [r.reason | some r in _firing]
