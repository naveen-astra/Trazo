package trazo.decision

import rego.v1

# Tool blocklist (TRZ-P6-02): deny any tool.call naming a tool on the
# blocklist, regardless of args or cost. `blocklisted_tools` is a
# `default` so a deployment can override it via its own
# `data.trazo.decision.blocklisted_tools`, without editing this file.

default blocklisted_tools := {"delete_database", "wire_transfer"}

deny contains {"policy_id": "tool_blocklist", "reason": reason} if {
	input.action.kind == "tool.call"
	input.action.tool_name in blocklisted_tools
	reason := sprintf("tool %q is on the blocklist", [input.action.tool_name])
}
