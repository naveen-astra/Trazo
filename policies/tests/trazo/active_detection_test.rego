package trazo.decision

import rego.v1

_active_detection_input := {
	"run_id": "run_1",
	"action": {
		"kind": "tool.call",
		"fingerprint": "sha256:aaaa",
		"tool_name": "send_email",
		"side_effect_class": "external",
		"projected_cost_usd": 0.1,
	},
	"run_context": {"cost_usd_so_far": 0.5, "active_detections": []},
}

test_allow_when_no_active_detections if {
	decision == "allow" with input as _active_detection_input
}

test_deny_external_tool_while_loop_detection_active if {
	stuck := object.union(_active_detection_input, {"run_context": object.union(_active_detection_input.run_context, {"active_detections": ["loop"]})})
	decision == "deny" with input as stuck
	policy_id == "active_detection_gate" with input as stuck
}

test_allow_read_only_tool_while_loop_detection_active if {
	read_only := object.union(_active_detection_input, {
		"action": object.union(_active_detection_input.action, {"side_effect_class": "read"}),
		"run_context": object.union(_active_detection_input.run_context, {"active_detections": ["loop"]}),
	})
	decision == "allow" with input as read_only
}

test_allow_external_tool_when_a_different_detection_is_active if {
	other := object.union(_active_detection_input, {"run_context": object.union(_active_detection_input.run_context, {"active_detections": ["budget"]})})
	decision == "allow" with input as other
}
