"""Simulator: an offline, scripted demo of the *whole* pipeline.

This is the key showcase of the project. It plays a short scene between a
(hypothetical) person and the buddy, then fast-forwards simulated time to
show the three proactive behaviors -- follow-up on an open topic, a
milestone check-in, and a mood check -- with zero network and zero API keys
(the retrieval fallback brain is used).

Run:

    python main.py simulate
"""

from __future__ import annotations

import time

from .base import Adapter


class SimulateAdapter(Adapter):
    name = "simulate"

    def __init__(self, manager, log: list[str] | None = None):
        super().__init__(manager)
        # Compress the pacing so the demo shows proactivity within seconds.
        manager.memory.follow_up_delay_s = 6.0   # open topic matures fast
        mgr = manager.proactivity
        mgr.pacing.min_silence_s = 3.0
        mgr.pacing.max_silence_s = 8.0
        mgr.pacing.budget_per_day = 100
        self._log = log if log is not None else []

    # ------------------------------------------------------------------
    def send(self, text: str) -> None:
        self._log.append(f"[{self.manager.persona.name}] {text}")

    def _say(self, who: str, text: str) -> None:
        self._log.append(f"[{who}] {text}")

    # ------------------------------------------------------------------
    def start(self) -> None:
        now = time.time()

        # --- act 1: a normal conversation -----------------------------
        self._say("You", "hey, you around?")
        reply = self.manager.handle_incoming("hey, you around?", now=now)
        self.send(reply)

        now += 40
        self._say("You", "my physics exam is on 2026-11-02, kinda stressed about it")
        reply = self.manager.handle_incoming(
            "my physics exam is on 2026-11-02, kinda stressed about it", now=now
        )
        self.send(reply)

        now += 300
        self._say("You", "anyway, gotta go, talk later")
        reply = self.manager.handle_incoming("anyway, gotta go, talk later", now=now)
        self.send(reply)

        # --- act 2: the buddy follows up on its own --------------------
        now += 20  # past follow_up_delay_s -> the open topic is due
        proactive = self.manager.tick(now=now)
        if proactive:
            self.send(proactive)

        # --- act 3: milestone day arrives ------------------------------
        # Jump to the exam date itself.
        exam_ts = time.mktime((2026, 11, 2, 9, 0, 0, 0, 0, -1))
        now = exam_ts + 1800
        proactive = self.manager.tick(now=now)
        if proactive:
            self.send(proactive)

        # --- act 4: a rough day for the person -------------------------
        self._say("You", "tbh i feel really tired and stressed today")
        reply = self.manager.handle_incoming(
            "tbh i feel really tired and stressed today", now=now
        )
        self.send(reply)

        now += 60
        self._say("You", "nothing's going right lol")
        reply = self.manager.handle_incoming("nothing's going right lol", now=now)
        self.send(reply)

        now += 20
        proactive = self.manager.tick(now=now)
        if proactive:
            self.send(proactive)

        print("=" * 60)
        print(" simulated chat -- Buddy vs. You (all offline, no API keys)")
        print("=" * 60)
        for line in self._log:
            print(line)
        print("=" * 60)
        print("notes: 'follow_up' fired on the exam topic, 'milestone' on")
        print("exam day, 'mood' after the rough messages. Plug in an LLM")
        print("backend (see README) and the same flow gets real language.")
