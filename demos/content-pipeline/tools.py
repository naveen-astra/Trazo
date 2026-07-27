"""Tools for the content-pipeline demo (TRZ-P3-03): deterministic canned
results (no network, no API cost — TRZ-P3-04's constraint on every demo).

Unlike the research-assistant (LangGraph) demo, these are plain CrewAI
tools (``crewai.tools.tool``), not wrapped with the SDK's ``@trace_tool``
escape hatch: CrewAI's own agent executor already emits
``ToolUsageStartedEvent``/``ToolUsageFinishedEvent`` for any tool an agent
calls, and TRZ-P3-01's adapter already captures those as ``tool.call`` —
no escape hatch needed here (the LangGraph demo needed one only for
memory operations, which no adapter auto-captures).
"""

from __future__ import annotations

from crewai.tools import tool

_SNIPPETS: dict[str, str] = {
    "overview": (
        "Trazo records agent runs as a sequence of typed events with fingerprints."
    ),
    "details": (
        "Every boundary-critical event (llm.call, tool.call, memory.read/write) "
        "carries a sha256 fingerprint of its normalized inputs."
    ),
    "examples": (
        "Example: instrument(crew).kickoff(...) traces a CrewAI run with zero "
        "code changes to the crew itself."
    ),
}

_STYLE_GUIDE = "House style: active voice, short sentences, no unexplained jargon."


@tool("web_search")
def web_search(query: str) -> str:
    """Search the web for a query; returns a short snippet."""
    lowered = query.lower()
    for keyword, snippet in _SNIPPETS.items():
        if keyword in lowered:
            return snippet
    return f"no notable results for '{query}'"


@tool("fetch_style_guide")
def fetch_style_guide() -> str:
    """Fetch the house style guide."""
    return _STYLE_GUIDE


@tool("word_count")
def word_count(text: str) -> int:
    """Count words in a piece of text — a real computation, not canned."""
    return len(text.split())
