"""Tests for Brain backends and the factory."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from social_buddy.core.brain import (
    OllamaBrain,
    OpenAIBrain,
    RetrievalBrain,
    get_brain,
)
from social_buddy.core.memory import MemoryBank


def test_retrieval_brain_uses_memory():
    m = MemoryBank()
    m.note("user loves eating hotpot")
    brain = RetrievalBrain(m, min_note_age=0.0)
    out = brain.generate(
        [{"role": "user", "content": "what do I like to eat?"}]
    )
    assert isinstance(out, str) and out.strip(), out
    assert "hotpot" in out, out


def test_retrieval_brain_ignores_fresh_notes():
    m = MemoryBank()
    m.note("user loves eating hotpot")
    brain = RetrievalBrain(m, min_note_age=3600.0)
    out = brain.generate(
        [{"role": "user", "content": "what do I like to eat?"}]
    )
    # The note is too fresh to quote as "before" -- generic reply instead.
    assert "hotpot" not in out


def test_retrieval_brain_proactive_line():
    m = MemoryBank()
    m.register_open_topic("my exam is on 2026-11-02", 1.0)
    brain = RetrievalBrain(m)
    out = brain.generate(
        [{"role": "user", "content": "(You are starting the conversation. "
         "Write the first message now.)"}]
    )
    assert "exam" in out, out


def test_retrieval_brain_generic_reply():
    m = MemoryBank()
    brain = RetrievalBrain(m)
    out = brain.generate([{"role": "user", "content": "haha nice"}])
    assert out.strip()


def test_backends_construct_without_network():
    b1 = OpenAIBrain(api_key="x", base_url="http://127.0.0.1:1", model="m")
    assert b1.model == "m"
    b2 = OllamaBrain(host="http://127.0.0.1:1", model="q")
    assert b2.model == "q"


def test_factory_falls_back_to_retrieval():
    for key in ("OPENAI_API_KEY", "OLLAMA_HOST", "SOCIAL_BUDDY_BRAIN"):
        os.environ.pop(key, None)
    brain = get_brain(MemoryBank())
    assert isinstance(brain, RetrievalBrain)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print("All brain tests PASSED.")
