"""ProactiveEngine: the reason *why* the buddy reaches out first.

A proactive message that has no reason feels like spam. The engine therefore
only ever fires when it can point at a real social cue:

1. follow_up     -- the human asked/mentioned something that was never closed.
                    "you said you had an exam this week -- how did it go?"
2. milestone     -- a dated event the human told us about is near (today).
3. mood          -- the human sounded down; a quick "you okay?" beats silence.
4. random_thought-- the buddy simply "thought of them" (rare, throttled hard).

Pacing keeps it human: a random inter-message delay, a daily budget, and a
"is it worth saying?" gate so the buddy never becomes a notification bot.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from .memory import MemoryBank


@dataclass
class ProactiveAction:
    kind: str          # follow_up | milestone | mood | random_thought
    reason: str        # human-readable, injected into the prompt
    topic: str = ""    # dedup key
    weight: int = 1    # priority: higher fires first


@dataclass
class Pacing:
    """How often the buddy may reach out on its own."""

    min_silence_s: float = 1200.0      # 20 min
    max_silence_s: float = 14400.0     # 4 h
    budget_per_day: int = 8            # hard cap of proactive msgs / day
    max_random_per_day: int = 2        # "thinking of you" is the rarest kind

    def next_delay(self, rng: random.Random) -> float:
        """Log-uniform sample in [min, max] -- feels like a person's rhythm."""
        lo, hi = self.min_silence_s, self.max_silence_s
        return math_exp_interval(lo, hi, rng)

    def can_fire(
        self,
        now: float,
        last_msg_ts: float,
        last_proactive_ts: float,
        today_count: int,
        random_count: int = 0,
    ) -> bool:
        if today_count >= self.budget_per_day:
            return False
        if now - last_msg_ts < self.min_silence_s:
            return False
        if now - last_proactive_ts < self.min_silence_s:
            return False
        if random_count >= self.max_random_per_day:
            return False
        return True


def math_exp_interval(lo: float, hi: float, rng: random.Random) -> float:
    """Uniform in log-space, clamped to [lo, hi]."""
    u = rng.random()
    return lo * (hi / lo) ** u


class ProactiveEngine:
    """Decides whether, and with what reason, the buddy should speak first."""

    def __init__(
        self,
        memory: MemoryBank,
        pacing: Pacing | None = None,
        rng: random.Random | None = None,
        mood_cooldown_s: float = 6 * 3600,
    ):
        self.memory = memory
        self.pacing = pacing or Pacing()
        self.rng = rng or random.Random()
        self.mood_cooldown_s = mood_cooldown_s
        self.last_mood_check: float = 0.0
        self.last_proactive_ts: float = 0.0
        self.today_proactive: int = 0
        self.today_random: int = 0
        self._day_key: str = ""

    # ------------------------------------------------------------------
    def decide(
        self,
        now: float | None = None,
        last_msg_ts: float | None = None,
        mood_score: int = 0,
        random_skip: float = 0.30,
    ) -> ProactiveAction | None:
        """Return an action to take now, or None to stay silent."""
        now = now if now is not None else time.time()
        last_msg_ts = last_msg_ts if last_msg_ts is not None else now
        self._roll_day(now)

        if not self.pacing.can_fire(
            now,
            last_msg_ts,
            self.last_proactive_ts,
            self.today_proactive,
            self.today_random,
        ):
            return None

        action = self._highest_priority(now, mood_score)
        if action is None:
            return None

        # "Is it worth saying?" gate -- skip low-priority kinds randomly.
        if action.weight <= 1 and self.rng.random() < random_skip:
            return None
        return action

    # ------------------------------------------------------------------
    def _highest_priority(self, now: float, mood_score: int) -> ProactiveAction | None:
        # 1) A dated milestone they told you about is near -- the strongest cue.
        near = self.memory.pending_milestones(now)
        if near:
            m = near[0]
            delta_days = (now - m["at"]) / 86400.0
            when = "today" if abs(delta_days) < 0.75 else (
                "soon" if delta_days < 0 else "just happened"
            )
            reason = f"their \"{m['title']}\" is {when}; check in warmly"
            return ProactiveAction(
                kind="milestone", reason=reason, topic=m["title"], weight=4
            )

        # 2) Follow up on something the human left open (newest first).
        due = self.memory.due_topics(now)
        if due:
            topic = due[-1]
            reason = (
                f"they asked/mentioned: \"{topic.text[:80]}\" and it was "
                f"left open; follow up naturally"
            )
            return ProactiveAction(
                kind="follow_up", reason=reason, topic=topic.keyword, weight=3
            )

        # 3) They seemed down recently and it has been a while.
        if mood_score <= -1 and (now - self.last_mood_check) >= self.mood_cooldown_s:
            return ProactiveAction(
                kind="mood",
                reason="they sounded down/upset recently; check in gently",
                weight=2,
            )

        # 4) Rarely, just "thinking of you".
        return ProactiveAction(
            kind="random_thought",
            reason="nothing specific -- just thinking of them",
            weight=1,
        )

    # ------------------------------------------------------------------
    def mark_sent(self, action: ProactiveAction, now: float | None = None) -> None:
        """Call after the message is actually delivered."""
        now = now if now is not None else time.time()
        self.last_proactive_ts = now
        self.today_proactive += 1
        if action.kind == "random_thought":
            self.today_random += 1
        if action.kind == "mood":
            self.last_mood_check = now
        if action.kind == "follow_up":
            for t in self.memory.open_topics:
                if t.keyword == action.topic:
                    t.asked = True
        if action.kind == "milestone":
            for m in self.memory.milestones:
                if m["title"] == action.topic:
                    m["fired"] = True

    # ------------------------------------------------------------------
    def _roll_day(self, now: float) -> None:
        key = time.strftime("%Y-%m-%d", time.localtime(now))
        if key != self._day_key:
            self._day_key = key
            self.today_proactive = 0
            self.today_random = 0
