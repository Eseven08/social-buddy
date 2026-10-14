"""Brain: pluggable language-model backends.

Three backends with the same interface:

- OpenAIBrain     -- any OpenAI-compatible /chat/completions endpoint
                     (OpenAI, DeepSeek, Moonshot, local vLLM, ...).
- OllamaBrain     -- local models via Ollama (free, offline).
- RetrievalBrain  -- dependency-free fallback that answers from memory.
                     Not smart, but it lets the entire pipeline (memory,
                     proactivity, adapters) run with zero keys and zero
                     network -- perfect for tests and for trying the demo.

Pick a backend with :func:`get_brain` based on environment variables.
"""

from __future__ import annotations

import os
import random

import requests

from .memory import MemoryBank


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
class Brain:
    """Language-model backend interface."""

    name: str = "base"

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.8,
        max_tokens: int = 160,
    ) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# OpenAI-compatible backend
# ---------------------------------------------------------------------------
class OpenAIBrain(Brain):
    name = "openai-compatible"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout: int = 60,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate(self, messages, temperature=0.8, max_tokens=160):
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Ollama backend (local, offline)
# ---------------------------------------------------------------------------
class OllamaBrain(Brain):
    name = "ollama"

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "qwen2.5:3b",
        timeout: int = 120,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate(self, messages, temperature=0.8, max_tokens=160):
        resp = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Retrieval fallback (no LLM required)
# ---------------------------------------------------------------------------
class RetrievalBrain(Brain):
    """Rule-based stand-in so the whole system runs without a model.

    It answers from what the memory knows:

    - If a message overlaps an *old* memory note strongly enough, it
      references it ("you said X before -- how did it turn out?").
    - Notes younger than ``min_note_age`` are treated as "just said now",
      so the fallback never quotes the message it is replying to.
    - Proactive messages reference the freshest open topic or milestone,
      which is what makes the offline demo feel real.
    """

    name = "retrieval-fallback"

    def __init__(self, memory: MemoryBank, seed: int = 7,
                 min_score: float = 0.12, min_note_age: float = 90.0):
        self.memory = memory
        self.min_score = min_score
        self.min_note_age = min_note_age
        self._rng = random.Random(seed)

    _openers = [
        "Haha, tell me more about that.",
        "Oh? That's interesting, how come?",
        "I see what you mean.",
        "Right, that reminds me of something we talked about before.",
        "Mm, go on -- I'm listening.",
        "Haha okay. What made you think of that?",
    ]
    _recall_templates = [
        "Oh right, you mentioned \"{hit}\" before -- is that still going on?",
        "That actually reminds me: you said \"{hit}\" earlier. How did that turn out?",
        "Wait, wasn't it you who said \"{hit}\" a while back?",
    ]
    _proactive_opener = [
        "Hey, just thinking of you -- what are you up to?",
        "Hey! Random thought, but how's your day going?",
        "Hey, haven't heard from you in a bit. All good?",
    ]

    def _last_human(self, messages) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return m["content"]
        return ""

    def _proactive_line(self) -> str:
        # 1) The freshest thing they left open.
        for t in reversed(self.memory.open_topics):
            if t.asked:
                continue
            return f'Hey, you mentioned "{t.text[:70]}" -- how is it going?'
        # 2) A dated milestone that is near.
        for m in self.memory.milestones:
            if m.get("fired"):
                continue
            return f"Thinking of you -- {m['title']} is around now. Hope it goes well!"
        # 3) If the person sounded down recently, that beats a random opener.
        from .memory import mood_of
        recent = self.memory.recent_turns(6)
        if sum(mood_of(t.text) for t in recent if t.role == "human") < 0:
            return "Hey, you sounded a bit down earlier -- everything okay?"
        return self._rng.choice(self._proactive_opener)

    def generate(self, messages, temperature=0.8, max_tokens=160):
        text = self._last_human(messages)
        if "You are starting the conversation" in text:
            return self._proactive_line()

        hits = self.memory.recall_with_scores(text, k=1)
        if hits:
            hit, score = hits[0]
            fresh = self.memory.note_age(hit) < self.min_note_age
            if score >= self.min_score and not fresh:
                tpl = self._rng.choice(self._recall_templates)
                return tpl.format(hit=hit[:60])
        return self._rng.choice(self._openers)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_brain(memory: MemoryBank | None = None) -> Brain:
    """Build the backend selected by environment variables.

    Order: SOCIAL_BUDDY_MODEL != "retrieval" and a key/host present
    -> OpenAI-compatible / Ollama; otherwise the retrieval fallback.
    """
    memory = memory or MemoryBank()
    mode = os.getenv("SOCIAL_BUDDY_BRAIN", "").strip().lower()
    if mode == "retrieval":
        return RetrievalBrain(memory)
    if mode == "openai":
        return OpenAIBrain(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("SOCIAL_BUDDY_MODEL", "gpt-4o-mini"),
        )
    if mode == "ollama":
        return OllamaBrain(
            host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            model=os.getenv("SOCIAL_BUDDY_MODEL", "qwen2.5:3b"),
        )
    if os.getenv("OPENAI_API_KEY"):
        return OpenAIBrain(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("SOCIAL_BUDDY_MODEL", "gpt-4o-mini"),
        )
    if os.getenv("OLLAMA_HOST") or mode == "auto-ollama":
        return OllamaBrain(
            host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            model=os.getenv("SOCIAL_BUDDY_MODEL", "qwen2.5:3b"),
        )
    return RetrievalBrain(memory)
