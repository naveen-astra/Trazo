"""LangGraph adapter (TRZ-P2-04).

Usage: ``from trazo.integrations.langgraph import instrument``.
Requires the ``langgraph`` extra: ``pip install trazo[langgraph]``.
"""

from trazo.integrations.langgraph.adapter import InstrumentedGraph, instrument

__all__ = ["InstrumentedGraph", "instrument"]
