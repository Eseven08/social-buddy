"""Tests for ConversationManager: learning, replies, proactive ticks."""

from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from social_buddy.core.brain import RetrievalBrain
from social_buddy.core.conversation import ConversationManager
from social_buddy.core.memory import MemoryBank
from social_buddy.core.proactivity import ProactiveEngine


def _manager(follow_up_s: float = 3.0) -> ConversationManager:
    mem = MemoryBank(follow_up_delay_s=follow_up_s)
    eng = ProactiveEngine(mem, rng=random.Random(2))
    eng.pacing.min_silence_s = 20.0
    eng.pacing.max_silence_s = 60.0
    eng.pacing.budget_per_day = 100
    return ConversationManager(memory=mem, brain=RetrievalBrain(mem), proactivity=eng)


def test_incoming_returns_reply_and_learns():
    cm = _manager()
    now = time.time()
    reply = cm.handle_incoming("my name is Eseven, my exam is on 2026-11-02", now=now)
    assert reply and isinstance(reply, str)
    assert cm.memory.facts.get("name") == "Eseven"
    assert len(cm.memory.milestones) == 1
    assert cm.memory.open_topics, "exam message should open a topic"
    assert cm.memory.recent_turns()[-1].role == "buddy"


def test_tick_silent_when_nothing_due():
    cm = _manager()
    now = time.time()
    cm.handle_incoming("hey", now=now)
    # Nothing open and too soon -> silent.
    assert cm.tick(now=now + 1) is None


def test_tick_fires_follow_up():
    cm = _manager(follow_up_s=5.0)
    now = time.time()
    cm.handle_incoming("my physics exam is on 2026-11-02", now=now)
    # After the follow-up delay, the buddy reaches out first.
    msg = cm.tick(now=now + 30)
    assert msg and isinstance(msg, str), msg
    assert cm.memory.recent_turns()[-1].proactive is True


def test_persona_prompt_includes_memory():
    from social_buddy.core.persona import Persona
    p = Persona(name="Buddy")
    sys_prompt = p.system_prompt("Known facts: city=Dongguan")
    assert "city=Dongguan" in sys_prompt
    assert "PROACTIVE MESSAGE" not in sys_prompt
    proactive = p.system_prompt("", proactive_note="they asked about X")
    assert "PROACTIVE MESSAGE" in proactive


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print("All conversation tests PASSED.")
