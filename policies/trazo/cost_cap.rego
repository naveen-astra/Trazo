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
		# %v, not %.2f: OPA's sprintf mis-formats a *whole*-valued number as
		# "%!f(int=N)" under %.2f (confirmed live — a genuinely whole-dollar
		# fixture cost like 81 reproduces it every time, regardless of
		# whether the value reaches here as a JSON int or a float that
		# happens to be whole; `+ 0.0` coercion does not fix it either).
		# %v costs the guaranteed two-decimal padding on whole amounts
		# ("$81" not "$81.00") but never leaks a raw Go format artifact
		# into a message a human reads.
		"run cost $%v already exceeds the $%v cap",
		[input.run_context.cost_usd_so_far, max_run_cost_usd],
	)
}

deny contains {"policy_id": "cost_cap", "reason": reason} if {
	projected := input.run_context.cost_usd_so_far + input.action.projected_cost_usd
	projected > max_run_cost_usd
	reason := sprintf(
		"projected run cost $%v would exceed the $%v cap",
		[projected, max_run_cost_usd],
	)
}
