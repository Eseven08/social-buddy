# social-buddy

An AI companion that lives inside your QQ and **talks like a real person**:
it replies with personality, remembers what you said, learns facts about you,
and — the key part — **messages you first** instead of waiting for a question.

```
 You:   my physics exam is on 2026-11-02, kinda stressed about it
 Buddy: Oh? That's interesting, how come?
 ...    (time passes)
 Buddy: Hey, you mentioned "my physics exam is on 2026-11-02" -- how is it going?
 ...    (exam day)
 Buddy: Thinking of you -- exam (2026-11-02) is around now. Hope it goes well!
```

No more Q&A-bot behavior. This is a **proactive social engine**: it picks the
right moment, finds a real reason to reach out, and sounds natural doing it.

## What makes it different

| typical chatbot | social-buddy |
|---|---|
| answers only when asked | **reaches out first** (follow-ups, milestone days, mood checks) |
| forgets everything | **remembers**: short-term window + facts + semantic recall |
| one memory for all chats | **per-conversation memory** (private chat ≠ each group) |
| "How can I help you?" | talks like a friend: short, warm, curious |
| needs an API key to demo | **fully offline demo** with a retrieval fallback brain |

## Features

- **Proactive engine** with real triggers, never random spam:
  - *follow-up* — you asked/mentioned something and it was left open
  - *milestone* — a dated event you told it about (exam, trip) is near
  - *mood* — you sounded down; a quick check-in beats silence
  - *thinking of you* — rare, heavily throttled
  - plus **pacing**: random inter-message delay, daily budget, "worth saying?" gate
- **Memory** in three layers:
  - short-term conversation window
  - long-term facts (`my name is ...`, `I am from ...` — extracted automatically
    from chat, or **pre-entered** in `profile.json`)
  - semantic recall via a tiny dependency-free TF-IDF index
- **Pluggable brain**: OpenAI-compatible API, local Ollama, or a no-key
  retrieval fallback (enough for tests + the offline demo)
- **QQ ready**: OneBot v11 (NapCatQQ etc.) adapter for private chats and
  group chats, with @-mention handling, whitelists and anti-spam probability
- **Runs 24/7**: Docker or systemd deployment so it keeps working while you
  are away from the computer
- **Zero external AI dependencies** for the core pipeline; only `requests`
  is needed for the LLM/QQ backends.

## Quickstart (no QQ, no API key — 30 seconds)

```bash
pip install -r requirements.txt

# scripted demo: watch the buddy follow up, wish you well on exam day,
# and check in when you are down -- all offline
python main.py simulate

# interactive terminal chat
python main.py cli --fast
```

The `simulate` output looks like this:

```
[You] my physics exam is on 2026-11-02, kinda stressed about it
[Buddy] Oh? That's interesting, how come?
[Buddy] Hey, you mentioned "my physics exam is on 2026-11-02, kinda stressed about it" -- how is it going?
[Buddy] Thinking of you -- exam (2026-11-02) is around now. Hope it goes well!
[You] tbh i feel really tired and stressed today
[Buddy] Hey, you sounded a bit down earlier -- everything okay?
```

Plug in a real LLM (below) and the same flow gets real language.

## Give it a brain

Pick one backend in `config.env` (copy from `config.example.env`):

```bash
# 1) any OpenAI-compatible API
SOCIAL_BUDDY_BRAIN=openai
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
SOCIAL_BUDDY_MODEL=gpt-4o-mini

# 2) local, free, offline (Ollama)
#    ollama pull qwen2.5:3b
SOCIAL_BUDDY_BRAIN=ollama
OLLAMA_HOST=http://localhost:11434
SOCIAL_BUDDY_MODEL=qwen2.5:3b
```

With neither set, the retrieval fallback brain is used — it answers from
memory so every demo and test still works offline.

## Tell it who you are (basic info)

Edit `profile.json` (template: `profile.example.json`) and the buddy starts
every conversation already knowing you:

```json
{
  "name": "Buddy",
  "relation": "a close, trustworthy friend",
  "seed_facts": {
    "name": "Eseven",
    "city": "Dongguan",
    "school": "Dongguan University of City College",
    "major": "Intelligent Manufacturing Engineering",
    "hobby": "gaming, AI projects, building things"
  }
}
```

It also keeps learning on its own from chat: `my favorite game is ...`,
`my exam is on 2026-11-02` → fact + milestone.

## Connect it to your real QQ account

The buddy logs into QQ **with your account** through a OneBot v11 bridge
(NapCatQQ is actively maintained; Lagrange.Core and LLOneBot also work),
so it can sit inside your group chats and DM your friends.

1. Install [NapCatQQ](https://napneko.github.io/) (or another OneBot bridge),
   log into a **dedicated QQ account** (never your main one — bridges violate
   QQ's ToS and carry a small restriction risk), and start its HTTP server
   (default `http://127.0.0.1:3000`).
2. Configure `config.env`:

```bash
SOCIAL_BUDDY_ONE_BOT_HTTP=http://127.0.0.1:3000
SOCIAL_BUDDY_QQ_SELF=10001            # the bot's own QQ
SOCIAL_BUDDY_QQ_TARGET=20002          # a friend's QQ to DM (optional)
SOCIAL_BUDDY_QQ_GROUP=30003           # group(s) to join, comma-separated (optional)
SOCIAL_BUDDY_QQ_WHITELIST=20002,40004 # QQs always answered (optional)
```

3. Run:

```bash
python main.py onebot
```

Group behavior, tuned to feel human:

- **@-mentioned** (or whitelisted friend speaks) → always replies, with an
  `@you` prefix for natural group etiquette
- **anyone else** speaks → the buddy joins with probability
  `SOCIAL_BUDDY_GROUP_REPLY_PROB` (default 0.2) and never two messages in a
  row (`45 s` cooldown)
- **proactive messages in groups are rare**: `SOCIAL_BUDDY_GROUP_BUDGET`
  (default 3/day) and a longer silence requirement
- every chat has its **own memory**: `buddy_memory_<conv>.json`

## Keep it running while your computer is off

The buddy needs an always-on host. Two options in `deploy/`:

- **Docker** (`docker compose up -d`): container with a data volume for memory
- **systemd** (`social-buddy.service`): run directly on a small VPS

Point `SOCIAL_BUDDY_ONE_BOT_HTTP` at the host running NapCatQQ
(`host.docker.internal:3000` on Docker Desktop). The buddy keeps remembering
and reaching out even when you are not at your computer.

## Project layout

```
social-buddy/
├── main.py                 # entry: cli | simulate | onebot
├── social_buddy/
│   ├── core/
│   │   ├── persona.py      # personality + "talk like a human" style rules
│   │   ├── memory.py       # short-term, facts, milestones, semantic recall
│   │   ├── brain.py        # OpenAI-compatible / Ollama / retrieval fallback
│   │   ├── proactivity.py  # pacing + triggers + "worth saying?" gate
│   │   ├── registry.py     # one buddy instance + memory per conversation
│   │   └── conversation.py # reply + proactive tick
│   └── adapters/
│       ├── cli.py          # terminal chat
│       ├── simulate.py     # offline scripted proactivity demo
│       └── onebot.py       # QQ via OneBot v11 (private + group)
├── tests/                  # memory / proactivity / brain / registry / adapters
├── deploy/                 # Docker + systemd for 24/7 operation
├── profile.example.json    # persona + seed facts template
├── config.example.env      # all environment variables documented
└── requirements.txt        # just requests
```

## How the proactive engine thinks

Every proactive message must pass a social reason test. The engine checks,
in priority order:

1. **Milestone near** (a dated event you told it about is today/soon) →
   highest priority, it is the strongest cue.
2. **Open topic** (you asked or mentioned something that was never closed) →
   follows up on the newest one.
3. **Mood** (recent messages sounded down, and it has been a while).
4. **Random thought** — rarely, and throttled to ~2/day.

Then the *pacing gate*: minimum silence (default 20 min / 1 h in groups),
a daily proactive budget, and a random skip for low-priority kinds. The
result is a buddy that reaches out with a reason, not on a timer.

## Testing

```bash
python tests/run_all.py
```

Covers fact/milestone/topic extraction, the recall index, pacing and trigger
logic, the registry's per-conversation isolation, adapter helpers and the
full simulator — all offline, no API keys.

## Extensions / ideas

- **LLM-assisted fact extraction**: let the brain mine richer facts and
  preferences from chat (currently heuristic + regex).
- **Embedding-based recall** instead of TF-IDF for much better memory hits.
- **Reaction/typing indicators** over OneBot for extra "humanness".
- **Conversation summaries**: compress long chats so memory never overflows.
- **Schedule-aware milestones**: read a calendar/ICS to know the person's day.

## License

MIT — see [LICENSE](LICENSE). Built for learning; use it however you like.
