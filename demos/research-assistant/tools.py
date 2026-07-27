"""Tools for the research-assistant demo (TRZ-P3-02): deterministic canned
results (no network, no API cost — TRZ-P3-04's constraint on every demo),
each wrapped with the SDK's public ``@trace_tool`` escape hatch.
"""

from __future__ import annotations

from trazo import trace_tool

_SNIPPETS: dict[str, str] = {
    "overview": (
        "Trazo is an observability, replay, and governance SDK for "
        "multi-agent AI systems."
    ),
    "architecture": (
        "Trazo's control plane ingests events over HTTP, publishes to Redis Streams, "
        "and persists to Postgres."
    ),
    "reliability": (
        "Trazo's replay engine substitutes recorded non-deterministic boundaries "
        "to reproduce a run exactly."
    ),
}

_DOCUMENTS: dict[str, str] = {
    "sdk-md": (
        "SDK.md: the public API is trazo.init, instrument(graph/crew), "
        "trace_tool, trace_llm."
    ),
    "events-md": (
        "EVENTS.md: every event carries run_id, seq, kind, and a fingerprint "
        "for the four replay-critical kinds."
    ),
}


@trace_tool(side_effect_class="external")
def web_search(query: str) -> str:
    """Search the web for a query; returns a short snippet."""
    lowered = query.lower()
    for keyword, snippet in _SNIPPETS.items():
        if keyword in lowered:
            return snippet
    return f"no notable results for '{query}'"


@trace_tool(side_effect_class="read")
def fetch_document(doc_id: str) -> str:
    """Fetch a reference document by id; returns its (canned) contents."""
    return _DOCUMENTS.get(doc_id, f"document '{doc_id}' not found")


@trace_tool(side_effect_class="read")
def calculator(expression: str) -> float:
    """Evaluate a simple arithmetic expression (``+``, ``-``, ``*``, ``/``,
    parentheses, numbers only — never Python's ``eval``, so this can't
    execute anything beyond arithmetic)."""
    import ast
    import operator

    ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
    }

    def _eval(node: ast.expr) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return ops[type(node.op)](_eval(node.operand))
        raise ValueError(f"unsupported expression: {ast.dump(node)}")

    return _eval(ast.parse(expression, mode="eval").body)
