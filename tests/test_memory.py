"""Tests for MemoryBank: facts, milestones, open topics, recall, persistence."""

from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from social_buddy.core.memory import (
    MemoryBank,
    extract_facts,
    extract_milestones,
    is_open_question,
    mood_of,
)


def test_extract_facts():
    facts = extract_facts("my name is Eseven and I am from Dongguan")
    pairs = dict(facts)
    assert pairs.get("name") == "Eseven", pairs
    assert "Dongguan" in str(pairs.get("from", "")), pairs


def test_extract_milestones():
    out = extract_milestones("my exam is on 2026-11-02")
    assert len(out) == 1
    title, ts = out[0]
    assert "2026-11-02" in title
    assert time.localtime(ts).tm_mon == 11


def test_open_question_heuristics():
    assert is_open_question("when is your birthday?")
    assert is_open_question("my exam is tomorrow")
    assert is_open_question("i will go to Guangzhou next week")
    assert not is_open_question("haha ok")


def test_mood_lexicon():
    assert mood_of("i feel really stressed and anxious") < 0
    assert mood_of("that's great, i'm so happy!") > 0
    assert mood_of("the sky is blue") == 0


def test_facts_and_milestones_learned():
    m = MemoryBank()
    m.learn_fact("city", "Dongguan")
    m.add_milestone("exam", 9999999999.0)
    assert m.facts["city"] == "Dongguan"
    assert len(m.milestones) == 1


def test_open_topic_registration_and_closure():
    m = MemoryBank(follow_up_delay_s=100.0)
    now = time.time()
    m.register_open_topic("my physics exam is on 2026-11-02", now)
    assert len(m.open_topics) == 1
    # Not due yet.
    assert m.due_topics(now + 50) == []
    # Due after the delay.
    due = m.due_topics(now + 200)
    assert len(due) == 1
    m.close_topic(due[0].keyword)
    assert m.open_topics == []


def test_recall_similarity():
    m = MemoryBank()
    m.note("the user loves eating hotpot")
    m.note("the user plays games all night")
    hits = m.recall("what does the user like to eat?", k=1)
    assert hits and "hotpot" in hits[0], hits


def test_persistence_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "mem.json")
        m1 = MemoryBank(store_path=path)
        m1.learn_fact("city", "Dongguan")
        m1.add_turn("human", "hello there")
        m1.save()

        m2 = MemoryBank(store_path=path)
        m2.load()
        assert m2.facts["city"] == "Dongguan"
        assert m2.recent_turns()[-1].text == "hello there"


def test_summary_nonempty():
    m = MemoryBank()
    m.learn_fact("name", "Eseven")
    m.add_turn("human", "hi")
    assert "Eseven" in m.summary()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print("All memory tests PASSED.")
