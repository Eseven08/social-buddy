"""ConversationRegistry: one buddy instance per conversation.

A QQ account lives in many chats at once -- private chats and groups. Every
chat gets its own ConversationManager with its own MemoryBank (so memories
from your friend's chat never leak into the group), while sharing the same
persona and the same LLM backend.

Group chats get stricter pacing by default: a real person does not message a
group as often as they DM a friend.
"""

from __future__ import annotations

import os

from .brain import Brain, RetrievalBrain
from .conversation import ConversationManager
from .memory import MemoryBank
from .persona import Persona
from .proactivity import Pacing, ProactiveEngine


class ConversationRegistry:
    def __init__(
        self,
        persona: Persona | None = None,
        brain: Brain | None = None,
        store_dir: str = ".",
        follow_up_delay_s: float = 300.0,
        group_budget_per_day: int = 3,
        group_min_silence_s: float = 3600.0,
    ):
        self.persona = persona or Persona()
        self.brain = brain  # may be None -> built per conversation
        self.store_dir = store_dir
        self.follow_up_delay_s = follow_up_delay_s
        self.group_budget_per_day = group_budget_per_day
        self.group_min_silence_s = group_min_silence_s
        self._convs: dict[str, ConversationManager] = {}

    def get(self, conv_id: str, group: bool = False) -> ConversationManager:
        """Get (and lazily create) the manager for a conversation."""
        if conv_id not in self._convs:
            store = os.path.join(
                self.store_dir, f"buddy_memory_{self._safe(conv_id)}.json"
            )
            mem = MemoryBank(
                store_path=store, follow_up_delay_s=self.follow_up_delay_s
            )
            mem.load()
            # Pre-enter the basic facts configured in profile.json.
            for key, value in self.persona.seed_facts.items():
                mem.learn_fact(key, str(value))

            if self.brain is None or isinstance(self.brain, RetrievalBrain):
                # A retrieval brain is bound to one memory, so each
                # conversation gets its own instance.
                brain: Brain = RetrievalBrain(mem)
            else:
                brain = self.brain  # stateless backend, safe to share

            pacing = Pacing(
                budget_per_day=(
                    self.group_budget_per_day if group else 8
                ),
                min_silence_s=(self.group_min_silence_s if group else 1200.0),
            )
            eng = ProactiveEngine(mem, pacing=pacing)
            self._convs[conv_id] = ConversationManager(
                persona=self.persona, memory=mem, brain=brain, proactivity=eng
            )
        return self._convs[conv_id]

    def save_all(self) -> None:
        for cm in self._convs.values():
            cm.memory.save()

    @staticmethod
    def _safe(name: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in name)[:48] or "default"
