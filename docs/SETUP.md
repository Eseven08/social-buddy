# Deploying social-buddy as a QQ group bot (from zero)

This guide walks a friend through setting up their own instance of **social-buddy**
so it joins their QQ group, replies in Chinese like a real person, remembers
conversation context, and occasionally speaks up on its own.

It is written for a plain Windows PC. Total time: roughly **30-60 minutes**
(depending on download speed).

## What you end up with

```
QQ group message
      │
      ▼
 NapCat (bridge, logs into your QQ small account)
      │  (polling every 4s, no event channel needed)
      ▼
 social-buddy (this repo, Python)
      │
      ▼
 Ollama (local LLM, e.g. qwen2.5:3b)  ── or ──  any OpenAI-compatible API
```

The bot runs on **your own machine**. If the PC is off, the bot is offline.
For 24/7 uptime, later move it to a cheap cloud VM (same steps, Linux).

---

## Step 0 — Prerequisites

- Windows 10/11 desktop PC (a GTX/RTX GPU helps Ollama but is not required —
  qwen2.5:3b also runs on CPU, just slower).
- A **QQ small account** you don't mind using for the bot (never use your main
  account — third-party bridges can trigger QQ risk control).
- [Python 3.10+](https://www.python.org/downloads/) (check with `python --version`).
- [Git](https://git-scm.com/download/win) (optional, used for cloning).

---

## Step 1 — Install Ollama and pull a Chinese model

1. Download the installer: <https://ollama.com/download/OllamaSetup.exe>
   (GitHub mirror if slow: `https://ghfast.top/https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe`).
2. Run it and install (default location is fine; to keep it off C:, install to `G:\Ollama`).
3. Open a terminal and pull a good small Chinese model:

   ```bat
   ollama pull qwen2.5:3b
   ```

   (~2 GB download; `ollama pull qwen2.5:7b` if you have 8 GB+ VRAM and want
   noticeably better quality.)

4. Verify:

   ```bat
   ollama run qwen2.5:3b "你好，介绍一下你自己"
   ```

   If it answers in Chinese, Ollama is ready. Keep Ollama running in the
   background (it auto-starts with Windows by default).

---

## Step 2 — Install NapCat (the QQ bridge)

NapCat lets the bot use your QQ account through the OneBot v11 protocol.
Use the **Shell** build (self-contained, no separate QQ install needed).

1. Download the latest release:
   <https://github.com/NapNeko/NapCatQQ/releases>
   Pick **NapCat.Shell.zip** under Assets (mirror prefix `ghfast.top/` if slow).
2. Unzip to a folder you won't move, e.g. `G:\NapCatOneKey\NapCat.52230.Shell`.
3. In that folder there is a **`NapCatWinBootMain.exe`**. Open a terminal there
   and start it **with your QQ number** for quick login:

   ```bat
   NapCatWinBootMain.exe 123456789   REM <-- your bot QQ number
   ```

   (First run may show a QR code to scan with your QQ phone app; after that it
   remembers the session and quick-logs in.)

4. Watch the console: you want a line like

   ```
   [NapCat] [WebUi] WebUi User Panel Url: http://127.0.0.1:6099/webui?token=xxxxxxxx
   ```

   Note the **token**. Keep this console window **open** — closing it kills the bot.

---

## Step 3 — Configure NapCat's network adapters

1. Open the Web UI in a browser: `http://127.0.0.1:6099/webui?token=xxxx`
   (use the token from the console).
2. Go to **Network** (网络).
3. Make sure these exist (create them if not):

   | Adapter | Type | Setting |
   |---|---|---|
   | **HTTP server** | name anything, e.g. `Eseven` | Host `127.0.0.1`, Port **3000**, enabled, token empty, message format **array** |
   | **HTTP client** | name `social-buddy` | URL `http://127.0.0.1:8765/`, enabled, message format **array** |

   The HTTP client is only a fallback — the bot mainly **polls** the server,
   so if the client never delivers events it still works.

---

## Step 4 — Get the bot code and configure it

```bat
git clone https://github.com/Eseven08/social-buddy.git
cd social-buddy
python -m pip install -r requirements.txt
```

Then:

```bat
copy config.example.env config.env
```

Open `config.env` in a text editor (Notepad is fine) and set:

```env
SOCIAL_BUDDY_BRAIN=ollama
OLLAMA_HOST=http://localhost:11434
SOCIAL_BUDDY_MODEL=qwen2.5:3b

SOCIAL_BUDDY_ONE_BOT_HTTP=http://127.0.0.1:3000
SOCIAL_BUDDY_QQ_SELF=123456789        # your bot QQ number
SOCIAL_BUDDY_QQ_GROUP=987654321       # the group the bot should join
SOCIAL_BUDDY_GROUP_REPLY_PROB=0.5     # how chatty when not @-mentioned
SOCIAL_BUDDY_TICK_SECONDS=30          # how often it checks to speak proactively
```

Optional — teach it about you (it remembers this and brings it up later):

```env
SOCIAL_BUDDY_NAME=Buddy
SOCIAL_BUDDY_PROFILE=profile.json
```

(`profile.json` is git-ignored — your data never gets pushed to GitHub.)

---

## Step 5 — Start everything

Double-click **`start-bot.bat`** (edit the two paths at the top of the file
first: `NAPCAT_DIR` and `BOT_DIR`). It launches:

1. the watchdog (auto-restarts NapCat and the bot if they die),
2. NapCat (quick login to your QQ),
3. the bot itself.

You should see two console windows appear. Keep them open.

---

## Step 6 — Verify

In your group, **@ your bot** and say something, e.g. `在吗`.

The bot replies within a few seconds (it polls every 4s). Without being
mentioned, it will chime in occasionally on its own (50% chance per message,
plus proactive messages after ~5 minutes of silence).

---

## FAQ / Troubleshooting

**Nothing happens when I @ the bot.**
Check the bot console window for a line like
`[onebot] poll started (interval 4s)`. If you see `poll error`, NapCat's HTTP
server (port 3000) is not up — check the NapCat window. If there are no logs at
all, the bot process died; the watchdog should restart it within ~30s.

**Replies are in English / sound robotic.**
That's the offline fallback brain (no model configured). Set
`SOCIAL_BUDDY_BRAIN=ollama` and make sure `ollama` is running. Test it first
with `ollama run qwen2.5:3b`.

**NapCat says "provided QQ path is invalid".**
The Shell build is self-contained — start `NapCatWinBootMain.exe` from inside
its own folder, never a bare `QQ.exe`. If a separate installer complains, just
use the Shell zip instead.

**The bot goes offline when I close the black window.**
NapCat and the bot both run in your PC's console windows. Closing either one
kills that side. The watchdog restarts them automatically while it is alive;
to keep 24/7 uptime you need a machine that is always on (cloud VM).

**I want it to be even more "human".**
Edit the persona in `social_buddy/core/persona.py` (name, style, traits), or
record more facts about yourself in `profile.json`. Both are plain text.

---

## Files you might touch

| Path | Purpose |
|---|---|
| `config.env` | behavior switches (prob, timing, QQ ids, backend) |
| `social_buddy/core/persona.py` | who the bot is and how it talks |
| `profile.json` | facts about you it should remember |
| `start-bot.bat` | one-click launcher (edit the two paths) |
