package trazo.decision

import rego.v1

_tool_blocklist_input := {
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

test_allow_for_a_tool_not_on_the_blocklist if {
	decision == "allow" with input as _tool_blocklist_input
}

test_deny_for_a_blocklisted_tool if {
	blocked := object.union(_tool_blocklist_input, {"action": object.union(_tool_blocklist_input.action, {"tool_name": "delete_database"})})
	decision == "deny" with input as blocked
	policy_id == "tool_blocklist" with input as blocked
}

test_non_tool_call_actions_are_never_blocked if {
	non_tool := object.union(_tool_blocklist_input, {"action": object.union(_tool_blocklist_input.action, {"kind": "llm.call", "tool_name": "delete_database"})})
	decision == "allow" with input as non_tool
}
