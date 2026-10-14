"""Tests for the adapters: CLI pacing, simulator output, OneBot helpers."""

from __future__ import annotations

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from social_buddy.adapters.cli import CliAdapter
from social_buddy.adapters.onebot import _plain_text, _was_mentioned
from social_buddy.adapters.simulate import SimulateAdapter
from social_buddy.core.brain import RetrievalBrain
from social_buddy.core.conversation import ConversationManager
from social_buddy.core.memory import MemoryBank
from social_buddy.core.proactivity import ProactiveEngine
from social_buddy.core.registry import ConversationRegistry


def _manager():
    mem = MemoryBank(follow_up_delay_s=6.0)
    eng = ProactiveEngine(mem, rng=random.Random(3))
    return ConversationManager(memory=mem, brain=RetrievalBrain(mem), proactivity=eng)


def test_cli_fast_compresses_pacing():
    cm = _manager()
    CliAdapter(cm, fast=True)
    assert cm.proactivity.pacing.min_silence_s == 4.0
    assert cm.memory.follow_up_delay_s == 8.0


def test_simulator_shows_all_proactive_kinds():
    cm = _manager()
    log: list[str] = []
    SimulateAdapter(cm, log=log).start()
    text = "\n".join(log)
    assert "[You]" in text and "[Buddy]" in text
    # The three proactive behaviors must appear (as Buddy-first messages).
    buddy_lines = [l for l in log if l.startswith("[Buddy]")]
    assert len(buddy_lines) >= 5, log
    assert "exam" in text.lower() or "2026-11-02" in text, text


def test_onebot_plain_text_flattening():
    segs = [
        {"type": "text", "data": {"text": "hello "}},
        {"type": "face", "data": {"id": "1"}},
        {"type": "text", "data": {"text": "world"}},
    ]
    assert _plain_text(segs) == "hello world"
    assert _plain_text("plain") == "plain"
    assert _plain_text([]) == ""


def test_onebot_mention_detection():
    bot = "123456789"
    segs = [
        {"type": "at", "data": {"qq": bot}},
        {"type": "text", "data": {"text": "what do you think?"}},
    ]
    assert _was_mentioned(segs, bot) is True
    assert _was_mentioned(segs, "other") is False
    assert _was_mentioned("plain text", bot) is False


def test_onebot_requires_bridge_config():
    with tempfile.TemporaryDirectory() as d:
        reg = ConversationRegistry(store_dir=d)
        from social_buddy.adapters.onebot import OneBotAdapter
        old = {
            k: os.environ.get(k)
            for k in (
                "SOCIAL_BUDDY_ONE_BOT_HTTP",
                "SOCIAL_BUDDY_QQ_TARGET",
                "SOCIAL_BUDDY_QQ_GROUP",
                "SOCIAL_BUDDY_QQ_SELF",
            )
        }
        for k in old:
            os.environ.pop(k, None)
        try:
            try:
                OneBotAdapter(reg)
                assert False, "should raise without target or group"
            except ValueError:
                pass
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print("All adapter tests PASSED.")
