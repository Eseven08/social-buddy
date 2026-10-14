"""MemoryBank: short-term context + long-term facts + semantic recall.

Three layers, mirroring how a human remembers a friend:

1. short_term  -- the last N turns of the current conversation window.
2. facts       -- explicit key/value facts ("lives in Dongguan",
                  "favorite game is 异环") extracted from chat, persisted.
3. notes       -- free-form semantic entries used for recall. Similarity is
                  computed with a tiny character-n-gram TF-IDF index, so the
                  whole system runs with zero external dependencies.

The bank also tracks *open topics*: things the human raised (questions,
future events) that were never closed. Those are the raw material for the
proactive engine -- "remember you mentioned X, how did it go?"
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
from collections import Counter, deque
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Turns and facts
# ---------------------------------------------------------------------------
@dataclass
class Turn:
    role: str  # "human" | "buddy"
    text: str
    ts: float = field(default_factory=time.time)
    proactive: bool = False


@dataclass
class OpenTopic:
    """A thing the human raised that the buddy may follow up on later."""

    text: str
    raised_ts: float
    follow_up_at: float  # earliest time a proactive follow-up may fire
    asked: bool = False  # buddy already asked about it once
    keyword: str = ""


# ---------------------------------------------------------------------------
# Tiny TF-IDF index (character n-grams, pure Python)
# ---------------------------------------------------------------------------
class _NgramIndex:
    """Bag-of-character-ngrams similarity index, no dependencies."""

    def __init__(self, n=(2, 3), min_df=1):
        self.n = n
        self.min_df = min_df
        self.docs: list[str] = []
        self.idf: dict[str, float] = {}
        self._built = False

    @staticmethod
    def _tokens(text: str) -> list[str]:
        text = unicodedata.normalize("NFKC", text).lower()
        text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", text)
        return text.split()

    def _ngrams(self, text: str) -> Counter:
        grams = Counter()
        for tok in self._tokens(text):
            if len(tok) == 1:
                grams[tok] += 1
                continue
            for size in self.n:
                for i in range(len(tok) - size + 1):
                    grams[tok[i : i + size]] += 1
        return grams

    def add(self, doc: str) -> None:
        self.docs.append(doc)
        self._built = False

    def _build(self) -> None:
        df: Counter = Counter()
        for doc in self.docs:
            df.update(set(self._ngrams(doc)))
        self.idf = {
            g: math.log((len(self.docs) + 1) / (1 + count)) + 1.0
            for g, count in df.items()
            if count >= self.min_df
        }
        self._built = True

    def _vec(self, doc: str) -> dict[str, float]:
        if not self._built:
            self._build()
        grams = self._ngrams(doc)
        norm = math.sqrt(sum((c * self.idf.get(g, 0.0)) ** 2 for g, c in grams.items()))
        if norm == 0:
            return {}
        return {g: c * self.idf.get(g, 0.0) / norm for g, c in grams.items()}

    def search(self, query: str, k: int = 3, exclude: set | None = None) -> list[tuple[str, float]]:
        """Return the k most similar docs to query, with cosine scores."""
        if not self.docs:
            return []
        qv = self._vec(query)
        if not qv:
            return []
        exclude = exclude or set()
        scored = []
        for i, doc in enumerate(self.docs):
            if i in exclude:
                continue
            dv = self._vec(doc)
            if not dv:
                continue
            common = set(qv) & set(dv)
            if not common:
                continue
            score = sum(qv[g] * dv[g] for g in common)
            scored.append((doc, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


# ---------------------------------------------------------------------------
# Heuristic knowledge extraction (works offline, no LLM needed)
# ---------------------------------------------------------------------------
_FACT_PATTERNS = [
    (re.compile(r"\bmy\s+([a-z][a-z0-9 _-]{0,40}?)\s+is\s+([^,.!?;]{2,80})", re.I), 1, 2),
    (re.compile(r"\bmy\s+([a-z][a-z0-9 _-]{0,40}?)\s+are\s+([^,.!?;]{2,80})", re.I), 1, 2),
    (re.compile(r"\bi\s+am\s+(from|in|at)\s+([^,.!?;]{2,60})", re.I), 1, 2),
]
_CUT_RE = re.compile(r"\s+(and|but|because|so|then)\s+", re.I)
_DATE_RE = re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_QUESTION_RE = re.compile(r"[?？]$|[?？]\s*$")
_FUTURE_RE = re.compile(
    r"\b(tomorrow|next week|this week|in \d+ days?|on .*20\d{2}|"
    r"后天|下周|月底|考|试|面试|deadline|exam|test|interview|trip|travel)\b",
    re.I,
)
_SELF_RE = re.compile(r"\b(i\s+will|i\'?ll|i\s+have\s+to|i\s+need\s+to|i\s+am\s+going\s+to|我要|我得|我打算)", re.I)

_MOOD_NEG = {
    "sad", "tired", "exhausted", "stressed", "anxious", "worried", "angry",
    "upset", "frustrated", "depressed", "lonely", "burned", "burned out",
    "overwhelmed", "崩溃", "累", "焦虑", "难过", "烦", "压力", "失眠",
}
_MOOD_POS = {
    "happy", "great", "excited", "awesome", "amazing", "glad", "proud",
    "good", "nice", "开心", "高兴", "棒", "爽", "顺利", "过了", "中了",
}


def extract_facts(text: str) -> list[tuple[str, str]]:
    """Heuristic fact extraction. Returns (key, value) pairs."""
    facts = []
    for pat, key_idx, val_idx in _FACT_PATTERNS:
        for m in pat.finditer(text):
            key = m.group(key_idx).strip().lower()
            val = _CUT_RE.split(m.group(val_idx).strip())[0].strip()
            val = re.sub(r"^(on|at|in)\s+", "", val, flags=re.I).strip()
            if key and val:
                facts.append((key, val))
    return facts


def extract_milestones(text: str) -> list[tuple[str, float]]:
    """Heuristic milestone extraction: (title, unix ts) for dated events."""
    out = []
    for m in _DATE_RE.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            ts = time.mktime((y, mo, d, 9, 0, 0, 0, 0, -1))
        except (OverflowError, ValueError):
            continue
        # Title: a few words before the date, e.g. "my physics exam is on ..."
        before = text[max(0, m.start() - 40) : m.start()]
        words = re.findall(r"[^\s,.;:!?]{2,}", before)
        title = " ".join(words[-3:])
        while re.search(r"\s+(is|are|on|in|at|for|to|my|the)\s*$", title, re.I):
            title = re.sub(r"\s+(is|are|on|in|at|for|to|my|the)\s*$", "", title, flags=re.I)
        if not title:
            title = f"an event on {y}-{mo:02d}-{d:02d}"
        out.append((f"{title} ({y}-{mo:02d}-{d:02d})", ts))
    return out


def mood_of(text: str) -> int:
    """Simple lexicon mood: +1 positive, -1 negative, 0 neutral."""
    words = set(re.findall(r"[a-z\u4e00-\u9fff]{2,}", text.lower()))
    return (1 if words & _MOOD_POS else 0) - (1 if words & _MOOD_NEG else 0)


_SMALLTALK = {
    "hey", "hi", "hello", "yo", "sup", "hiya", "haha", "lol", "ok", "okay",
    "well", "so", "anyway", "around", "there", "you", "are", "u", "in", "on",
    "what", "up", "how", "going", "today", "bye", "later", "good", "night",
    "morning",
}


def is_open_question(text: str) -> bool:
    """A message the human asked and the buddy probably should follow up on."""
    t = text.strip()
    tokens = [w.strip(",.!?~ ") for w in re.split(r"[\s,]+", t) if w.strip(",.!?~ ")]
    if len(tokens) <= 3 and all(w.lower() in _SMALLTALK for w in tokens):
        return False  # small talk ("hey, you around?") is not a topic
    return bool(_QUESTION_RE.search(text)) or bool(_FUTURE_RE.search(text)) or bool(_SELF_RE.search(text))


# ---------------------------------------------------------------------------
# The memory bank
# ---------------------------------------------------------------------------
class MemoryBank:
    def __init__(
        self,
        window: int = 12,
        store_path: str | None = None,
        follow_up_delay_s: float = 300.0,
    ):
        self.window = window
        self.store_path = store_path
        self.follow_up_delay_s = follow_up_delay_s
        self.short_term: deque[Turn] = deque(maxlen=window)
        self.facts: dict[str, str] = {}
        self.milestones: list[dict] = []  # {"title", "at", "fired"}
        self.notes: list[str] = []
        self._note_ts: dict[str, float] = {}
        self.open_topics: list[OpenTopic] = []
        self._index = _NgramIndex()
        for n in self.notes:
            self._index.add(n)

    # -- persistence -----------------------------------------------------
    def save(self) -> None:
        if not self.store_path:
            return
        os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)
        data = {
            "facts": self.facts,
            "milestones": self.milestones,
            "notes": self.notes,
            "open_topics": [t.__dict__ for t in self.open_topics],
            "short_term": [t.__dict__ for t in list(self.short_term)[-6:]],
        }
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def load(self) -> None:
        if not self.store_path or not os.path.exists(self.store_path):
            return
        with open(self.store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.facts = data.get("facts", {})
        self.milestones = data.get("milestones", [])
        self.notes = data.get("notes", [])
        for n in self.notes:
            self._index.add(n)
            self._note_ts.setdefault(n, 0.0)
        self.open_topics = [
            OpenTopic(**t) for t in data.get("open_topics", [])
        ]
        for t in data.get("short_term", []):
            self.short_term.append(Turn(**t))

    # -- writing --------------------------------------------------------
    def add_turn(self, role: str, text: str, proactive: bool = False) -> None:
        self.short_term.append(Turn(role=role, text=text, proactive=proactive))

    def learn_fact(self, key: str, value: str) -> None:
        key = key.strip().lower()
        if key and value.strip() and self.facts.get(key) != value.strip():
            self.facts[key] = value.strip()
            note = f"fact: {key} = {value.strip()}"
            if note not in self.notes:
                self.notes.append(note)
                self._index.add(note)
                self._note_ts[note] = time.time()

    def add_milestone(self, title: str, at: float) -> None:
        if not any(m["title"] == title for m in self.milestones):
            self.milestones.append({"title": title, "at": at, "fired": False})

    def note(self, text: str) -> None:
        if text and text not in self.notes:
            self.notes.append(text)
            self._index.add(text)
            self._note_ts[text] = time.time()

    def note_age(self, text: str, now: float | None = None) -> float:
        """Seconds since a note was created (0.0 for old/unknown notes)."""
        now = now if now is not None else time.time()
        return now - self._note_ts.get(text, 0.0)

    def register_open_topic(self, text: str, now: float) -> None:
        """Remember a question/future event raised by the human."""
        # Avoid flooding: don't open a topic for every single message.
        if not is_open_question(text):
            return
        key = self._topic_key(text)
        if self.open_topics:
            last = self.open_topics[-1]
            if _topic_overlap(last.keyword, key) > 0.6 and now - last.raised_ts < 300:
                return
        self.open_topics.append(
            OpenTopic(
                text=text,
                raised_ts=now,
                follow_up_at=now + self.follow_up_delay_s,
                keyword=key,
            )
        )

    def close_topic(self, keyword: str | None = None) -> None:
        """Close a topic once the human replies to a follow-up (or it is done)."""
        if keyword is None:
            if self.open_topics:
                self.open_topics.pop(0)
            return
        self.open_topics = [t for t in self.open_topics if keyword not in t.keyword]

    @staticmethod
    def _topic_key(text: str) -> str:
        words = re.findall(r"[0-9a-z\u4e00-\u9fff]{3,}", text.lower())
        return " ".join(dict.fromkeys(words))[:60]

    # -- reading ---------------------------------------------------------
    def recall(self, query: str, k: int = 3) -> list[str]:
        return [doc for doc, _ in self.recall_with_scores(query, k)]

    def recall_with_scores(self, query: str, k: int = 3) -> list[tuple[str, float]]:
        """Like recall, but returns (doc, cosine_score) pairs."""
        return self._index.search(query, k)

    def due_topics(self, now: float) -> list[OpenTopic]:
        return [t for t in self.open_topics if now >= t.follow_up_at and not t.asked]

    def pending_milestones(self, now: float) -> list[dict]:
        window = 24 * 3600  # +/- 1 day around the date
        return [
            m for m in self.milestones
            if not m.get("fired") and abs(now - m["at"]) <= window
        ]

    def recent_turns(self, n: int | None = None) -> list[Turn]:
        n = n or self.window
        return list(self.short_term)[-n:]

    def summary(self, now: float | None = None, max_facts: int = 8) -> str:
        """Human-readable summary for the prompt."""
        lines = []
        if self.facts:
            top = list(self.facts.items())[:max_facts]
            lines.append("Known facts: " + "; ".join(f"{k}={v}" for k, v in top))
        if self.open_topics:
            pending = " | ".join(t.text[:50] for t in self.open_topics[:3])
            lines.append("Open topics they raised: " + pending)
        recent = self.recent_turns(6)
        if recent:
            chat = " / ".join(f"{t.role}: {t.text[:60]}" for t in recent)
            lines.append("Recent chat: " + chat)
        return "\n".join(lines)


def _topic_overlap(a: str, b: str) -> float:
    """Token overlap ratio of two topic keys (0..1)."""
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))
