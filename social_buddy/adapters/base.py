"""Adapter interface: how the conversation engine talks to a platform."""

from __future__ import annotations

from ..core.conversation import ConversationManager


class Adapter:
    """Base class for a chat platform (QQ, terminal, simulator, ...)."""

    name = "base"

    def __init__(self, manager: ConversationManager):
        self.manager = manager

    def send(self, text: str) -> None:
        """Deliver one outbound message to the platform."""
        raise NotImplementedError

    def start(self) -> None:
        """Run the adapter (blocks)."""
        raise NotImplementedError
