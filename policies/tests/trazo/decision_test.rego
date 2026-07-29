package trazo.decision

import rego.v1

# Combination logic only (deny overrides escalate overrides allow) --
# each starter policy's own contribution to `deny`/`escalate` is tested
# in its own _test.rego file.

test_allow_when_nothing_fires if {
	decision == "allow" with deny as set() with escalate as set()
}

test_deny_wins_over_escalate if {
	decision == "deny" with deny as {{"policy_id": "a", "reason": "x"}} with escalate as {{"policy_id": "b", "reason": "y"}}
}

test_escalate_when_only_escalate_fires if {
	decision == "escalate" with deny as set() with escalate as {{"policy_id": "b", "reason": "y"}}
}

test_policy_id_joins_sorted_firing_policy_ids if {
	policy_id == "a,c" with deny as {{"policy_id": "c", "reason": "z"}, {"policy_id": "a", "reason": "x"}} with escalate as set()
}

test_policy_id_empty_when_nothing_fires if {
	policy_id == "" with deny as set() with escalate as set()
}

test_reasons_collects_firing_reasons if {
	reasons == ["x"] with deny as {{"policy_id": "a", "reason": "x"}} with escalate as set()
}
