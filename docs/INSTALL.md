# social-buddy — Quick Install Guide

A personal QQ chatbot with an AI brain (Ollama local model), long-term memory and
human-like group chat behaviour. This guide gets it running in ~10 minutes.

## 1. Requirements

- Windows 10/11 (a Linux/macOS setup works too, commands differ slightly)
- Python 3.10+ installed and on PATH
- (Optional but recommended) A spare QQ account for the bot

## 2. Install

```powershell
# 1. clone the repo
git clone https://github.com/Eseven08/social-buddy.git
cd social-buddy

# 2. create venv and install dependencies
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Give it a brain (local, free, offline)

```powershell
# install Ollama (portable, no admin needed):
# download the zip from https://github.com/ollama/ollama/releases, extract anywhere
# then start it:
ollama serve
# in a second terminal, pull the model and import it:
ollama pull qwen2.5:3b
```

## 4. Configure

```powershell
copy config.example.env config.env
# edit config.env:
#   SOCIAL_BUDDY_BRAIN=ollama
#   SOCIAL_BUDDY_MODEL=qwen2.5:3b
#   SOCIAL_BUDDY_QQ_GROUP=<your group id>
#   SOCIAL_BUDDY_QQ_WHITELIST=<your QQ id>   (the bot always replies to you)
```

## 5. Connect QQ (NapCat)

1. Install [NapCat](https://github.com/NapNeko/NapCatQQ) for your QQ version.
2. Start NapCat and log in with the bot's QQ account (scan the QR code).
3. In NapCat, enable the **OneBot v11 HTTP server** on port `3000`.
4. Start the bot:

```powershell
python main.py onebot
```

The bot is now live in your group.

## 6. One-click launcher

Create `start.bat` (or use the provided one):

```bat
@echo off
start "" ollama serve
start "" python main.py onebot
```

Double-click it to start everything.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Bot not replying | check NapCat HTTP server is running on 3000 (`netstat -ano \| findstr 3000`) |
| Model not found | `ollama list` — if empty, run `ollama pull qwen2.5:3b` |
| Replies are robotic | clear `buddy_memory_*.json` (old test replies pollute memory) |
| Ports busy | edit `SOCIAL_BUDDY_WEBHOOK_PORT` / NapCat port in config.env |
