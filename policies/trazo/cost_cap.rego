package trazo.decision

import rego.v1

# Cost-cap (TRZ-P6-02): deny once a run's cumulative cost already
# exceeds the configured cap, or once this action's own projected cost
# would push it over -- "absolute + projected" per TASKS/PHASE_6.md's
# DoD. `max_run_cost_usd` is a `default` so a deployment can override it
# by providing its own `data.trazo.decision.max_run_cost_usd` (OPA's
# standard override-a-default mechanism), without editing this file.

default max_run_cost_usd := 5.0

deny contains {"policy_id": "cost_cap", "reason": reason} if {
	input.run_context.cost_usd_so_far > max_run_cost_usd
	reason := sprintf(
		"run cost $%.2f already exceeds the $%.2f cap",
		[input.run_context.cost_usd_so_far, max_run_cost_usd],
	)
}

deny contains {"policy_id": "cost_cap", "reason": reason} if {
	projected := input.run_context.cost_usd_so_far + input.action.projected_cost_usd
	projected > max_run_cost_usd
	reason := sprintf(
		"projected run cost $%.2f would exceed the $%.2f cap",
		[projected, max_run_cost_usd],
	)
}
