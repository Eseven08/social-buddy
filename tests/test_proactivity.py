"""Tests for ProactiveEngine: pacing, triggers, dedup, budget."""

from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from social_buddy.core.memory import MemoryBank
from social_buddy.core.proactivity import Pacing, ProactiveEngine


def _engine(**kw):
    return ProactiveEngine(MemoryBank(), rng=random.Random(1), **kw)


def test_pacing_gate_blocks_immediate_refire():
    p = Pacing(min_silence_s=100.0, max_silence_s=100.0, budget_per_day=8)
    now = 1_000_000.0
    assert not p.can_fire(now, last_msg_ts=now, last_proactive_ts=0, today_count=0)
    assert p.can_fire(now + 101, last_msg_ts=now, last_proactive_ts=now - 200,
                      today_count=0)


def test_pacing_budget_cap():
    p = Pacing(min_silence_s=1.0, max_silence_s=1.0, budget_per_day=2)
    assert not p.can_fire(100, last_msg_ts=50, last_proactive_ts=90,
                          today_count=2)


def test_follow_up_fires_after_delay_and_only_once():
    eng = _engine()
    now = time.time()
    eng.memory.register_open_topic("my exam is on 2026-11-02", now)
    # Too early -> silent.
    assert eng.decide(now=now + 1, last_msg_ts=now - 5000) is None
    # Make it due.
    eng.memory.open_topics[0].follow_up_at = now + 5
    eng.memory.open_topics[0].raised_ts = now
    act = eng.decide(now=now + 10, last_msg_ts=now - 5000)
    assert act is not None and act.kind == "follow_up", act
    eng.mark_sent(act, now=now + 10)
    # After being asked, it should not fire again for the same topic.
    eng.memory.open_topics[0].asked = True
    act2 = eng.decide(now=now + 20, last_msg_ts=now + 10)
    assert act2 is None or act2.kind != "follow_up"


def test_milestone_fires_near_date():
    eng = _engine()
    now = time.time()
    eng.memory.add_milestone("my exam", now + 3600)  # 1 h away
    act = eng.decide(now=now + 1800, last_msg_ts=now - 5000)
    assert act is not None and act.kind == "milestone", act
    eng.mark_sent(act, now=now + 1800)
    assert eng.memory.milestones[0]["fired"] is True


def test_mood_fires_with_cooldown():
    eng = _engine(mood_cooldown_s=1000.0)
    now = time.time()
    act = eng.decide(now=now, last_msg_ts=now - 5000, mood_score=-2)
    assert act is not None and act.kind == "mood", act
    eng.mark_sent(act, now=now)
    # Cooldown: not again immediately.
    act2 = eng.decide(now=now + 1, last_msg_ts=now - 5000, mood_score=-2)
    assert act2 is None or act2.kind != "mood"


def test_random_thought_is_rare_and_budgeted():
    eng = _engine()
    eng.proactivity = None  # placeholder to keep linters quiet
    now = time.time()
    # Force a random_thought outcome by clearing triggers.
    eng.memory.open_topics.clear()
    eng.memory.milestones.clear()
    acts = []
    for _ in range(50):
        a = eng.decide(now=now, last_msg_ts=now - 5000, random_skip=0.0)
        if a:
            acts.append(a)
            eng.mark_sent(a, now=now)
        now += 100
    kinds = {a.kind for a in acts}
    assert "random_thought" in kinds, acts
    assert eng.today_random <= eng.pacing.max_random_per_day


def test_daily_budget_resets_per_day():
    eng = _engine()
    now = time.time()
    eng.today_proactive = eng.pacing.budget_per_day
    eng.last_proactive_ts = now - 99999
    assert eng.decide(now=now + 1, last_msg_ts=now - 99999) is None
    # Next day: budget resets.
    tomorrow = now + 90000
    assert eng.decide(now=tomorrow, last_msg_ts=tomorrow - 99999) is not None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print("All proactivity tests PASSED.")
