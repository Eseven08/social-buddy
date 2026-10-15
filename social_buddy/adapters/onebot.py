"""OneBot v11 adapter: connect the buddy to a real QQ account.

OneBot v11 is a standard HTTP/WebSocket protocol implemented by QQ protocol
bridges such as NapCatQQ (actively maintained), Lagrange.Core, and
LLOneBot. You run the bridge locally next to a QQ client, it logs into the
QQ account for you, and this adapter talks to it over HTTP:

    outbound   POST <ONE_BOT_HTTP>/send_private_msg | /send_group_msg
    inbound    an HTTP webhook this adapter exposes, receiving message
               events that the bridge forwards (config: ONE_BOT_WEBHOOK).

Group behavior (the buddy lives inside your QQ in group chats):

- When the bot is @-mentioned (or messaged by a whitelisted friend) it
  replies, addressing the mentioner with an @ for natural group etiquette.
- When a non-whitelisted member talks, the buddy joins with a small
  probability (GROUP_REPLY_PROB) -- enough to feel present, not spammy.
- Proactive messages in groups are much rarer (GROUP_BUDGET per day) and
  every conversation (private chat / group) has its own memory, so nothing
  leaks between chats.

Security note: non-official QQ bridges violate QQ's ToS and carry a small
risk of account restriction. Use a dedicated / throwaway account, never
your main one.

Required env vars (see config.example.env):

    SOCIAL_BUDDY_ONE_BOT_HTTP   e.g. http://127.0.0.1:3000  (bridge address)
    SOCIAL_BUDDY_QQ_SELF        the bot's own QQ number (to ignore itself)
    SOCIAL_BUDDY_QQ_TARGET      optional: a friend's QQ to DM
    SOCIAL_BUDDY_QQ_WHITELIST   optional: comma-separated QQs always answered
    SOCIAL_BUDDY_QQ_GROUP       optional: a group id to join
    SOCIAL_BUDDY_WEBHOOK_PORT   local port for receiving events (default 8765)
    SOCIAL_BUDDY_TICK_SECONDS   proactive check interval (default 60)
    SOCIAL_BUDDY_GROUP_REPLY_PROB   reply probability in groups (0.0-1.0)
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from .base import Adapter
from ..core.registry import ConversationRegistry


class OneBotAdapter(Adapter):
    name = "onebot"

    def __init__(self, registry: ConversationRegistry):
        self.registry = registry
        self.http = os.getenv("SOCIAL_BUDDY_ONE_BOT_HTTP", "http://127.0.0.1:3000").rstrip("/")
        self.bot_qq = os.getenv("SOCIAL_BUDDY_QQ_SELF", "").strip()
        self.target_qq = os.getenv("SOCIAL_BUDDY_QQ_TARGET", "").strip()
        self.group_id = os.getenv("SOCIAL_BUDDY_QQ_GROUP", "").strip()
        self.whitelist = {
            q.strip() for q in os.getenv("SOCIAL_BUDDY_QQ_WHITELIST", "").split(",") if q.strip()
        }
        if self.target_qq:
            self.whitelist.add(self.target_qq)
        self.webhook_port = int(os.getenv("SOCIAL_BUDDY_WEBHOOK_PORT", "8765"))
        self.tick_seconds = int(os.getenv("SOCIAL_BUDDY_TICK_SECONDS", "60"))
        self.group_reply_prob = float(os.getenv("SOCIAL_BUDDY_GROUP_REPLY_PROB", "0.2"))
        self.poll_seconds = int(os.getenv("SOCIAL_BUDDY_POLL_SECONDS", "4"))
        self._rng = random.Random()
        self._last_group_reply: dict[str, float] = {}  # group -> ts
        self._group_cooldown = 60.0
        self._last_seqs: dict[str, int | None] = {}  # group -> last seen message time
        self._seen_ids: dict[str, set[int]] = {}  # group -> recently seen message ids
        if not self.target_qq and not self.group_id:
            raise ValueError(
                "OneBot adapter needs SOCIAL_BUDDY_QQ_TARGET (or SOCIAL_BUDDY_QQ_GROUP)"
            )

    # ------------------------------------------------------------------
    # outbound
    # ------------------------------------------------------------------
    _RISK_WORDS = (
        "六四", "天安门事件", "法轮", "翻墙", "代刷", "刷单", "兼职日结",
        "裸聊", "约炮", "卖号", "租号", "发卡", "博彩", "菠菜", "赌博",
        "跑分", "洗钱", "毒品", "冰毒", "摇头丸", "枪支", "买凶",
    )

    @staticmethod
    def _risk_hit(text: str) -> bool:
        t = text.lower()
        return any(w in t for w in OneBotAdapter._RISK_WORDS)

    def send_to(self, text: str, group: bool = False, conv_id: str = "", at_qq: str = "") -> None:
        if self._risk_hit(text):
            print("[onebot] blocked risky reply", flush=True)
            return
        # Human-like typing delay: never reply instantly, never at a fixed rate.
        time.sleep(self._rng.uniform(1.5, 4.0))
        if group:
            endpoint, payload = "send_group_msg", {"group_id": int(conv_id or self.group_id)}
        else:
            endpoint, payload = "send_private_msg", {"user_id": int(conv_id or self.target_qq)}
        # NapCat (this build) requires message segments as an array.
        message: list = []
        if at_qq:
            message.append({"type": "at", "data": {"qq": str(at_qq)}})
        message.append({"type": "text", "data": {"text": text}})
        payload["message"] = message
        resp = requests.post(f"{self.http}/{endpoint}", json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") not in ("ok", None):
            print(f"[onebot] send failed: {data}", flush=True)

    def send(self, text: str) -> None:
        """Adapter interface: DM the configured target (or the group)."""
        if self.group_id:
            self.send_to(text, group=True)
        else:
            self.send_to(text, group=False)

    # ------------------------------------------------------------------
    # inbound webhook
    # ------------------------------------------------------------------
    def start(self) -> None:
        print(f"[onebot] listening on :{self.webhook_port} for events...", flush=True)
        print(f"[onebot] outbound via {self.http}", flush=True)
        if self.group_id:
            print(f"[onebot] group mode: {self.group_id} (reply prob "
                  f"{self.group_reply_prob}, whitelist {sorted(self.whitelist)})", flush=True)
        threading.Thread(target=self._tick_loop, daemon=True).start()
        # Pull mode: query the bridge API for new group messages directly.
        # Some bridge builds never deliver HTTP-client events, so polling is
        # the reliable path; the webhook above still helps when it does work.
        if self.group_id:
            threading.Thread(target=self._poll_loop, daemon=True).start()
        server = ThreadingHTTPServer(("0.0.0.0", self.webhook_port), _make_handler(self))
        server.serve_forever()

    def _poll_loop(self) -> None:
        """Poll get_group_msg_history and feed new messages through on_event.

        The bridge's message_seq values are NOT monotonic (Tencent message ids
        come back out of order), so we track progress by message timestamp and
        de-duplicate with recently-seen message ids.
        """
        print(f"[onebot] poll started (interval {self.poll_seconds}s)", flush=True)
        time.sleep(2)  # let the bridge settle before the first baseline read
        while True:
            try:
                for gid in (self.group_id.split(",") if self.group_id else []):
                    gid = gid.strip()
                    if not gid:
                        continue
                    resp = requests.post(
                        f"{self.http}/get_group_msg_history",
                        json={"group_id": int(gid), "count": 20},
                        timeout=10,
                    )
                    data = resp.json()
                    msgs = (data.get("data") or {}).get("messages") or []
                    if not msgs:
                        continue
                    top = max(int(m.get("time", 0)) for m in msgs)
                    baseline = self._last_seqs.get(gid)
                    seen = self._seen_ids.setdefault(gid, set())
                    if baseline is None:
                        # First read: only record the baseline, do not replay history.
                        self._last_seqs[gid] = top
                        for m in msgs:
                            seen.add(int(m.get("message_id", 0)))
                        continue
                    self._last_seqs[gid] = top
                    fresh = []
                    for m in msgs:
                        mid = int(m.get("message_id", 0))
                        if str(m.get("user_id", "")) == self.bot_qq:
                            continue
                        if int(m.get("time", 0)) > baseline or (
                            int(m.get("time", 0)) == baseline and mid not in seen
                        ):
                            fresh.append(m)
                            seen.add(mid)
                    for m in sorted(fresh, key=lambda x: int(x.get("time", 0))):
                        evt = {
                            "post_type": "message",
                            "message_type": "group",
                            "group_id": gid,
                            "user_id": m.get("user_id"),
                            "self_id": self.bot_qq,
                            "message": m.get("message"),
                            "raw_message": m.get("raw_message", ""),
                        }
                        self.on_event(evt)
            except Exception as exc:  # noqa: BLE001 -- keep the loop alive
                print(f"[onebot] poll error: {exc}", flush=True)
            time.sleep(self.poll_seconds)

    def _tick_loop(self) -> None:
        while True:
            time.sleep(self.tick_seconds)
            try:
                # Private target, if configured.
                if self.target_qq:
                    self._maybe_proactive(conv_id=self.target_qq, group=False)
                # Groups.
                for gid in (self.group_id.split(",") if self.group_id else []):
                    gid = gid.strip()
                    if gid:
                        self._maybe_proactive(conv_id=gid, group=True)
            except Exception as exc:  # noqa: BLE001 -- keep the loop alive
                print(f"[onebot] tick error: {exc}", flush=True)

    def _maybe_proactive(self, conv_id: str, group: bool) -> None:
        cm = self.registry.get(conv_id, group=group)
        msg = cm.tick()
        if msg:
            print(f"[onebot] proactive ({'group' if group else 'dm'}): {msg}", flush=True)
            self.send_to(msg, group=group, conv_id=conv_id)

    # ------------------------------------------------------------------
    def on_event(self, event: dict) -> None:
        if event.get("post_type") != "message":
            return
        user_id = str(event.get("user_id", ""))
        if self.bot_qq and user_id == self.bot_qq:
            return  # our own message

        message_type = event.get("message_type")
        if message_type == "private":
            if not self.target_qq or user_id != self.target_qq:
                return
            text = _plain_text(event.get("message"))
            if not text:
                return
            cm = self.registry.get(self.target_qq, group=False)
            reply = cm.handle_incoming(text, sender=user_id)
            if reply:
                print(f"[onebot] dm reply: {reply}", flush=True)
                self.send_to(reply, group=False, conv_id=self.target_qq)
            return

        if message_type == "group":
            group_id = str(event.get("group_id", ""))
            text = _plain_text(event.get("message"))
            mentioned = _was_mentioned(event.get("message"), self.bot_qq)
            whitelisted = user_id in self.whitelist
            # Called by name (小樱 / 山田樱) -> must reply too.
            name_called = ("小樱" in text) or ("山田樱" in text)
            must_reply = mentioned or whitelisted or name_called
            if not text and not must_reply:
                return
            if not text:
                # Bare @ with no text -- answer anyway so the bot never feels dead.
                reply = "在呢，怎么了？"
                print(f"[onebot] group reply (mention, no text): {reply}", flush=True)
                self.send_to(reply, group=True, conv_id=group_id, at_qq=user_id)
                self._last_group_reply[group_id] = time.time()
                return

            if not must_reply:
                # Join the group chat occasionally, but never spam.
                if not self._group_cooldown_ok(group_id):
                    return
                if self._rng.random() >= self.group_reply_prob:
                    return

            cm = self.registry.get(group_id, group=True)
            reply = cm.handle_incoming(text, sender=user_id)
            if not reply:
                return
            at_qq = user_id if must_reply else ""
            print(f"[onebot] group reply (mention={mentioned} whitelist={whitelisted} name={name_called}): {reply}", flush=True)
            self.send_to(reply, group=True, conv_id=group_id, at_qq=at_qq)
            self._last_group_reply[group_id] = time.time()
            return

    def _group_cooldown_ok(self, group_id: str) -> bool:
        last = self._last_group_reply.get(group_id, 0.0)
        return (time.time() - last) >= self._group_cooldown


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _plain_text(message) -> str:
    """OneBot messages are strings or segment lists -- flatten to text."""
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        parts = []
        for seg in message:
            if seg.get("type") == "text":
                parts.append(seg.get("data", {}).get("text", "").strip())
        return " ".join(p for p in parts if p).strip()
    return ""


def _was_mentioned(message, bot_qq: str) -> bool:
    """True if the bot was @-mentioned (at segment with its QQ)."""
    if not bot_qq:
        return False
    if isinstance(message, list):
        for seg in message:
            if seg.get("type") == "at":
                qq = str(seg.get("data", {}).get("qq", ""))
                if qq == bot_qq:
                    return True
    return False


def _make_handler(adapter: OneBotAdapter):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            try:
                event = json.loads(body.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                event = {}
            try:
                adapter.on_event(event)
            except Exception as exc:  # noqa: BLE001
                print(f"[onebot] event error: {exc}", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *args):  # silence default logging
            pass

    return Handler
