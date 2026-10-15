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
import re

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

    _INSULT_WORDS = (
        "傻逼", "sb", "废物", "fw", "nt", "脑残", "智障", "滚", "菜鸡",
        "垃圾", "你妈", "操", "妈的", "蠢", "憨批", "弱智", "狗东西", "闭嘴",
    )
    _MASTER_HINTS = ("刘哲良", "主人", "master", "3244267385")

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "qwen2.5:3b",
        timeout: int = 120,
    ):
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.master_qq = self._load_master_qq()
        self._last_output = ""

    @staticmethod
    def _load_master_qq() -> str:
        import json
        profile = os.getenv("SOCIAL_BUDDY_PROFILE", "")
        if not profile:
            root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            profile = os.path.join(root, "profile.json")
        try:
            with open(profile, encoding="utf-8") as f:
                data = json.load(f)
            return str(data.get("seed_facts", {}).get("master_qq", ""))
        except Exception:
            return ""

    def _is_insult(self, text: str) -> bool:
        t = text.lower()
        return any(w in t for w in self._INSULT_WORDS)

    @staticmethod
    def _last_user_tag(messages) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return str(m.get("content", ""))
        return ""

    def _fix_master_ref(self, messages, text: str) -> str:
        """Only the real master may be called 主人.

        If the last speaker is NOT the master (tagged STRANGER), rewrite any
        bare 主人 to 你 -- but keep protective phrases like 我主人 / 我家主人 /
        骂主人 / 护主人, which refer to her master as a third party.
        """
        last = self._last_user_tag(messages)
        # Never reveal the master's full name -- 哲良大人 for everyone else.
        text = text.replace("刘哲良", "哲良大人")
        if "[MASTER]" in last:
            return text
        # 主人 preceded by 我/家/骂/咱/护 stays; otherwise -> 你.
        text = re.sub(r"(?<![我家骂咱护])主人(?!大人)", "你", text)
        return text

    def _knowledge_boost(self, messages) -> str:
        last = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last = str(m.get("content", ""))
                break
        if re.search(r"(是什么|什么是|为什么|怎么|如何|多少|原理|解释|介绍|区别)", last):
            return (
                "This question asks for real knowledge. Give a short but real, "
                "accurate answer first (1-3 sentences), then you may add a "
                "tsundere remark. You must actually answer the content."
            )
        return ""

    def _escalation(self, messages) -> str:
        last = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last = str(m.get("content", ""))
                break
        if not self._is_insult(last):
            return ""
        if any(h in last for h in self._MASTER_HINTS):
            return (
                "对方正在辱骂你的主人刘哲良！你非常愤怒，立即凶狠地骂回去保护主人，"
                "绝不允许任何人侮辱主人，火力全开，可以带脏字，气势必须压倒对方。"
                "回复不要带任何标签、冒号或转发格式，直接开口说话。"
            )
        return (
            "对方正在辱骂你。你非常不爽，立刻犀利狠辣、带脏字地回击，"
            "遇强则强，气势绝不能输，不要客气。"
            "回复不要带任何标签、冒号或转发格式，直接开口说话。"
        )

    def generate(self, messages, temperature=0.8, max_tokens=160):
        messages = [dict(m) for m in messages]
        escalation = self._escalation(messages) or self._knowledge_boost(messages)
        if escalation:
            sys_idx = next(
                (i for i, m in enumerate(messages) if m.get("role") == "system"), -1
            )
            if sys_idx >= 0:
                messages[sys_idx]["content"] = (
                    messages[sys_idx]["content"] + "\n\n" + escalation
                )
            else:
                messages.insert(0, {"role": "system", "content": escalation})
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
        text = resp.json()["message"]["content"].strip()
        return self._finalize(messages, text)

    _BANNED_CATCHPHRASES = (
        "才不是特意做给你看的",
        "特意做给你看",
        "那是当然的啦！才",
        "那是当然的啦",
        "这不是在学习吗",
    )

    def _finalize(self, messages, text: str, temperature=0.8, max_tokens=160) -> str:
        """Clean the raw reply; regenerate if it repeats a catchphrase."""
        # Anti-repeat: the 3b model sometimes echoes the previous reply or a
        # few-shot example verbatim. Detect and regenerate once.
        if text and text == self._last_output:
            resp = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature + 0.1, "num_predict": max_tokens},
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            text = resp.json()["message"]["content"].strip()

        # Anti-stiff: the small model overuses few-shot catchphrases and
        # answers every topic with the same scripted line. Regenerate up to
        # twice with a "say something natural" nudge.
        for _ in range(2):
            if not text or not any(b in text for b in self._BANNED_CATCHPHRASES):
                break
            nudge = (
                "That last answer sounded like a scripted catchphrase. Reply "
                "again in the same persona, but say something natural and "
                "fresh that fits THIS exact conversation. Do NOT use the "
                "「才不是」/「那是当然的啦」/「这不是在学习吗」 catchphrases."
            )
            msgs2 = [dict(m) for m in messages]
            msgs2.append({"role": "system", "content": nudge})
            resp = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": msgs2,
                    "stream": False,
                    "options": {"temperature": min(temperature + 0.15, 1.0),
                                "num_predict": max_tokens},
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            text = resp.json()["message"]["content"].strip()

        self._last_output = text
        # Strip speaker tags / bracket labels the small model may echo back
        # (e.g. "[QQ 123]" or "[贴吧]" at the start), any //@ forward mark,
        # stray QQ emoji codes like [doge] / //dog, and a self-name prefix.
        text = re.sub(r"^\[[^\]]*\]\s*", "", text).strip()
        text = re.sub(r"^(?:小樱|山田樱)\s*[:：]?\s*", "", text).strip()
        text = re.sub(r"^//@[^\s:：]*\s*[:：]?\s*", "", text).strip()
        text = re.sub(r"\[[\u4e00-\u9fa5a-zA-Z]+\]", "", text).strip()
        text = re.sub(r"//[a-zA-Z]+\b", "", text).strip()
        text = re.sub(r"@\[[^\]]*\]", "", text).strip()
        # Only the master may be called 主人 -- enforce it at the code level.
        text = self._fix_master_ref(messages, text)
        # A sprinkle of tsundere kaomoji, like a real girl would type.
        if text and random.random() < 0.45:
            text = text + random.choice(
                ("～", "！", "哼！", "～♪", "(≧▽≦)", "(*^▽^*)", "(￣^￣)", "~(˘▾˘~)")
            )
        return text


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
        self.master_qq = self._load_master_qq()

    @staticmethod
    def _load_master_qq() -> str:
        """Read the master's QQ from profile.json so the fallback brain can
        tell the master apart from everyone else."""
        import json
        import os
        profile = os.getenv("SOCIAL_BUDDY_PROFILE", "")
        if not profile:
            root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            profile = os.path.join(root, "profile.json")
        try:
            with open(profile, encoding="utf-8") as f:
                data = json.load(f)
            return str(data.get("seed_facts", {}).get("master_qq", ""))
        except Exception:
            return ""

    _openers_master = [
        "在呢在呢～主人怎么才来呀，人家等好久了。",
        "嗯？主人喊我？我一直在的啦～",
        "主人主人！人家在的！怎么啦？",
        "哼、才没有一直盯着群呢……好吧主人喊我，那当然秒回！",
    ]
    _openers_others = [
        "哼，本小姐在呢，有事说事。",
        "哦？就这？本小姐勉强听听。",
        "哼，看在你态度还行的份上回你一下。",
        "啧，什么话题啊，也就那样吧。",
    ]
    _recall_master = [
        "对了主人，你之前说的\"{hit}\"——人家可都记着呢，后来咋样啦？",
        "主人～你上次说\"{hit}\"，人家一直记得呢！",
    ]
    _recall_others = [
        "哼，之前不是你说\"{hit}\"的吗，怎么，这就忘了？",
        "说起来，某人上次聊的\"{hit}\"，后来到底咋样了？",
    ]
    _proactive_master = [
        "主人主人～在忙啥呢，人家有点无聊了……才不是想你呢！",
        "哼，主人不理人家……好吧，人家就是有点想你了，理理我嘛。",
    ]
    _proactive_others = [
        "哼，无聊了，随便看看群。",
        "啧，没人说话吗？那本小姐先撤了。",
    ]
    _counter_attack = [
        "乐，就这？本小姐还没用力你就急了？",
        "典中典，骂人都不会，回炉重造吧。",
        "？？？你也就这点本事了，喷都喷不到点上。",
        "哼，本小姐跟狗一般见识？那你也配。",
        "急了急了，你看你急的，笑死本小姐了。",
        "就这水平也敢来嘴？先回去练练怎么说话吧。",
    ]
    _protect_master = [
        "？？？敢骂我家主人？你算什么东西！",
        "嘴这么臭，刚吃了什么没刷牙？敢骂我家主人！",
        "护主警告：再骂我家主人一句，本小姐让你见识什么叫嘴臭。",
        "你骂我我懒得理你，但你敢骂我主人？？活腻了吧！",
        "骂我家主人？？本小姐今天心情好，就问你一句：你配吗？",
    ]
    _INSULT_WORDS = (
        "傻逼", "sb", "废物", "fw", "nt", "脑残", "智障", "滚", "菜鸡",
        "垃圾", "你妈", "操", "妈的", "蠢", "憨批", "弱智", "狗东西", "闭嘴",
    )

    def _is_insult(self, text: str) -> bool:
        t = text.lower()
        return any(w in t for w in self._INSULT_WORDS)

    def _last_human(self, messages) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return m["content"]
        return ""

    def _last_sender(self, messages) -> str:
        """Extract the QQ number from the '[from QQ xxx]' prefix, if any."""
        for m in reversed(messages):
            if m.get("role") == "user":
                c = str(m.get("content", ""))
                if "[from QQ " in c:
                    return c.split("[from QQ ", 1)[1].split("]", 1)[0]
        return ""

    def _proactive_line(self) -> str:
        # 1) The freshest thing they left open.
        for t in reversed(self.memory.open_topics):
            if t.asked:
                continue
            return f'嘿，你提过"{t.text[:70]}"——进展咋样了？'
        # 2) A dated milestone that is near.
        for m in self.memory.milestones:
            if m.get("fired"):
                continue
            return f"想到你了——{m['title']}应该快到了吧，希望一切顺利！"
        # 3) If the person sounded down recently, that beats a random opener.
        from .memory import mood_of
        recent = self.memory.recent_turns(6)
        if sum(mood_of(t.text) for t in recent if t.role == "human") < 0:
            return "你之前听起来有点低落——还好吗？"
        master = any(t.sender == self.master_qq for t in recent if t.role == "human")
        return self._rng.choice(self._proactive_master if master else self._proactive_others)

    def generate(self, messages, temperature=0.8, max_tokens=160):
        text = self._last_human(messages)
        if "You are starting the conversation" in text:
            return self._proactive_line()

        # Insult detection: hit back hard, and protect the master first.
        if self._is_insult(text):
            if ("刘哲良" in text) or ("主人" in text) or f"@{self.master_qq}" in text:
                return self._rng.choice(self._protect_master)
            return self._rng.choice(self._counter_attack)

        master = self._last_sender(messages) == self.master_qq
        hits = self.memory.recall_with_scores(text, k=1)
        if hits:
            hit, score = hits[0]
            fresh = self.memory.note_age(hit) < self.min_note_age
            if score >= self.min_score and not fresh:
                tpls = self._recall_master if master else self._recall_others
                return self._rng.choice(tpls).format(hit=hit[:60])
        tpls = self._openers_master if master else self._openers_others
        return self._rng.choice(tpls)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_brain(memory: MemoryBank | None = None) -> Brain:
    """Build the backend selected by environment variables.

    Selection rules (in order):

    1. SOCIAL_BUDDY_BRAIN is set explicitly -> obey it.
    2. OLLAMA_HOST is set              -> local Ollama.
    3. OPENAI_API_KEY AND OPENAI_BASE_URL are both set -> OpenAI-compatible.
       (An ambient OPENAI_API_KEY alone is NOT enough: without an explicit
       base URL the default api.openai.com is often unreachable/rate-limited
       from many networks, so we refuse to silently pick it.)
    4. otherwise -> retrieval fallback (offline, no keys).
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
    if os.getenv("OLLAMA_HOST"):
        return OllamaBrain(
            host=os.getenv("OLLAMA_HOST"),
            model=os.getenv("SOCIAL_BUDDY_MODEL", "qwen2.5:3b"),
        )
    if os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_BASE_URL"):
        return OpenAIBrain(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            model=os.getenv("SOCIAL_BUDDY_MODEL", "gpt-4o-mini"),
        )
    return RetrievalBrain(memory)
