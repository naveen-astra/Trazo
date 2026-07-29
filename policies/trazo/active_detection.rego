package trazo.decision

import rego.v1

# Active-detection gate (TRZ-P6-02): deny external-side-effect tool
# calls while a loop detection is active for this run (AI_DEBUGGER.md --
# a run already flagged as stuck should not be left free to keep taking
# real-world actions). Scoped to `side_effect_class == "external"` only:
# a stuck run should stop *doing things to the outside world*, not be
# barred from read-only tools it might use to get itself unstuck.

deny contains {"policy_id": "active_detection_gate", "reason": reason} if {
	input.action.kind == "tool.call"
	input.action.side_effect_class == "external"
	"loop" in input.run_context.active_detections
	reason := "loop detection is active for this run; external tool calls are blocked until it clears"
}
