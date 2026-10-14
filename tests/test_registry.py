"""Tests for ConversationRegistry: per-conversation memory + seed facts."""

from __future__ import annotations

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from social_buddy.core.persona import Persona
from social_buddy.core.registry import ConversationRegistry


def test_registry_isolates_conversations():
    with tempfile.TemporaryDirectory() as d:
        reg = ConversationRegistry(store_dir=d)
        a = reg.get("friend_1")
        b = reg.get("group_999", group=True)
        a.memory.learn_fact("secret", "from friend 1")
        assert "secret" not in b.memory.facts
        # Same id -> same manager (shared memory).
        assert reg.get("friend_1") is a


def test_group_pacing_is_stricter():
    with tempfile.TemporaryDirectory() as d:
        reg = ConversationRegistry(
            store_dir=d,
            group_budget_per_day=3,
            group_min_silence_s=3600.0,
        )
        dm = reg.get("friend_1")
        grp = reg.get("group_999", group=True)
        assert dm.proactivity.pacing.budget_per_day > grp.proactivity.pacing.budget_per_day
        assert grp.proactivity.pacing.min_silence_s >= dm.proactivity.pacing.min_silence_s


def test_seed_facts_preentered():
    with tempfile.TemporaryDirectory() as d:
        persona = Persona(name="Buddy", seed_facts={"name": "Eseven", "city": "Dongguan"})
        reg = ConversationRegistry(persona=persona, store_dir=d)
        cm = reg.get("friend_1")
        assert cm.memory.facts["name"] == "Eseven"
        assert cm.memory.facts["city"] == "Dongguan"


def test_persistence_between_creations():
    with tempfile.TemporaryDirectory() as d:
        reg1 = ConversationRegistry(store_dir=d)
        cm1 = reg1.get("friend_1")
        cm1.memory.learn_fact("name", "Eseven")
        reg1.save_all()

        reg2 = ConversationRegistry(store_dir=d)
        cm2 = reg2.get("friend_1")
        assert cm2.memory.facts["name"] == "Eseven"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print("All registry tests PASSED.")
