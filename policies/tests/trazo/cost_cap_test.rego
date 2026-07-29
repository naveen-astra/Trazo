package trazo.decision

import rego.v1

_cost_cap_input := {
	"run_id": "run_1",
	"action": {
		"kind": "tool.call",
		"fingerprint": "sha256:aaaa",
		"tool_name": "web_search",
		"side_effect_class": "read",
		"projected_cost_usd": 0.1,
	},
	"run_context": {"cost_usd_so_far": 0.5, "active_detections": []},
}

test_allow_when_well_under_cap if {
	decision == "allow" with input as _cost_cap_input
}

test_deny_when_already_over_cap if {
	over := object.union(_cost_cap_input, {"run_context": {"cost_usd_so_far": 5.5, "active_detections": []}})
	decision == "deny" with input as over
	policy_id == "cost_cap" with input as over
}

test_deny_when_projected_cost_would_exceed_cap if {
	near_cap := object.union(_cost_cap_input, {
		"run_context": {"cost_usd_so_far": 4.95, "active_detections": []},
		"action": object.union(_cost_cap_input.action, {"projected_cost_usd": 1.0}),
	})
	decision == "deny" with input as near_cap
}

test_allow_when_projected_cost_stays_under_cap if {
	fine := object.union(_cost_cap_input, {
		"run_context": {"cost_usd_so_far": 1.0, "active_detections": []},
		"action": object.union(_cost_cap_input.action, {"projected_cost_usd": 0.5}),
	})
	decision == "allow" with input as fine
}
