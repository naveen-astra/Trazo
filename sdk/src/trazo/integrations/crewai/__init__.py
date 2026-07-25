"""CrewAI adapter (TRZ-P3-01).

Usage: ``from trazo.integrations.crewai import instrument``.
Requires the ``crewai`` extra: ``pip install trazo[crewai]``.
"""

from trazo.integrations.crewai.adapter import InstrumentedCrew, instrument

__all__ = ["InstrumentedCrew", "instrument"]
