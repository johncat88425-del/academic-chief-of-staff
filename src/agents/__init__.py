"""Multi-agent system for the Academic Chief of Staff."""

from .base import BaseAgent
from .orchestrator import OrchestratorAgent
from .context_parser import ContextParserAgent
from .outlook_engine import OutlookEngineAgent
from .deep_researcher import DeepResearcherAgent
from .synthesizer import SynthesizerAgent

__all__ = [
    "BaseAgent",
    "OrchestratorAgent",
    "ContextParserAgent",
    "OutlookEngineAgent",
    "DeepResearcherAgent",
    "SynthesizerAgent",
]
