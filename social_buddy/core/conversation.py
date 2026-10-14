"""ConversationManager: the brain behind every message the buddy sends.

Two entry points used by every adapter:

- handle_incoming(text) -> reply
    A message from the human arrives: update memory, extract facts and open
    topics, then generate a reply through the brain.

- tick() -> message | None
    Called periodically while the buddy is idle. If the proactive engine
    thinks it is time to reach out, a contextual proactive message is
    generated and returned. None means "stay silent".

Both paths go through the same prompt builder, so replies and proactive
messages share one personality and one memory.
"""

from __future__ import annotations

import time

from .brain import Brain, RetrievalBrain
from .memory import (
    MemoryBank,
    extract_facts,
    extract_milestones,
    mood_of,
)
from .persona import Persona
from .proactivity import ProactiveAction, ProactiveEngine


class ConversationManager:
    def __init__(
        self,
        persona: Persona | None = None,
        memory: MemoryBank | None = None,
        brain: Brain | None = None,
        proactivity: ProactiveEngine | None = None,
    ):
        self.persona = persona or Persona()
        self.memory = memory or MemoryBank()
        self.brain = brain or RetrievalBrain(self.memory)
        self.proactivity = proactivity or ProactiveEngine(self.memory)
        self.last_msg_ts: float = time.time()

    # ------------------------------------------------------------------
    # Incoming message
    # ------------------------------------------------------------------
    def handle_incoming(self, text: str, now: float | None = None) -> str:
        now = now if now is not None else time.time()
        text = (text or "").strip()
        if not text:
            return ""

        self.last_msg_ts = now
        self.memory.add_turn("human", text)

        # Learn from what they said.
        for key, value in extract_facts(text):
            self.memory.learn_fact(key, value)
        for title, at in extract_milestones(text):
            self.memory.add_milestone(title, at)
            self.memory.note(f"milestone: {title}")
        self.memory.register_open_topic(text, now)

        messages = self._messages(now)
        reply = self.brain.generate(messages, temperature=0.85)
        reply = self._clean(reply)
        if reply:
            self.memory.add_turn("buddy", reply)
        return reply

    # ------------------------------------------------------------------
    # Proactive tick
    # ------------------------------------------------------------------
    def tick(self, now: float | None = None) -> str | None:
        now = now if now is not None else time.time()
        recent = self.memory.recent_turns(8)
        mood_score = sum(mood_of(t.text) for t in recent if t.role == "human")

        action = self.proactivity.decide(
            now=now,
            last_msg_ts=self.last_msg_ts,
            mood_score=mood_score,
        )
        if action is None:
            return None

        messages = self._messages(now, proactive=action)
        text = self.brain.generate(messages, temperature=0.9)
        text = self._clean(text)
        if not text:
            return None

        self.memory.add_turn("buddy", text, proactive=True)
        self.proactivity.mark_sent(action, now)
        return text

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------
    def _messages(self, now: float, proactive: ProactiveAction | None = None) -> list[dict]:
        summary = self.memory.summary(now)
        note = proactive.reason if proactive else ""
        system = self.persona.system_prompt(summary, proactive_note=note)
        msgs = [{"role": "system", "content": system}]

        for t in self.memory.recent_turns(10):
            role = "user" if t.role == "human" else "assistant"
            msgs.append({"role": role, "content": t.text})

        if proactive is not None:
            # The reason was already injected into the system prompt; the
            # trailing user message just asks the model to produce the opener.
            msgs.append(
                {
                    "role": "user",
                    "content": "(You are starting the conversation. "
                    "Write the first message now.)",
                }
            )
        return msgs

    @staticmethod
    def _clean(text: str) -> str:
        """Trim and strip the model's filler/formatting."""
        text = (text or "").strip()
        if text.startswith('"') and text.endswith('"') and len(text) > 2:
            text = text[1:-1].strip()
        return text[:280]
