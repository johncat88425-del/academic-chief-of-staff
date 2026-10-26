"""Base agent class providing shared infrastructure for all agents."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from src.memory import SQLiteStore, VectorStore
from src.utils.llm import GeminiClient

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all agents in the system."""

    def __init__(
        self,
        name: str,
        sqlite_store: SQLiteStore,
        vector_store: VectorStore,
        llm: GeminiClient,
    ):
        self.name = name
        self.db = sqlite_store
        self.vectors = vector_store
        self.llm = llm
        self.logger = logging.getLogger(f"agent.{name}")

    @abstractmethod
    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute a task and return the result."""
        ...

    async def send_to_agent(self, target: str, message: dict[str, Any]) -> None:
        """Send a message to another agent via the orchestrator."""
        self.logger.info(f"[{self.name}] -> [{target}]: {message.get('action', 'unknown')}")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}'>"
