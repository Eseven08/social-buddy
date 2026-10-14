#!/usr/bin/env python3
"""Entry point for social-buddy.

Usage:
    python main.py cli [--fast]
    python main.py simulate
    python main.py onebot
    python main.py --config my.env cli

Subcommands:
    cli        interactive chat in the terminal
    simulate   offline scripted demo showing proactive behavior
    onebot     connect to QQ through a OneBot v11 bridge (NapCatQQ, ...)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from social_buddy.adapters.cli import CliAdapter  # noqa: E402
from social_buddy.adapters.simulate import SimulateAdapter  # noqa: E402
from social_buddy.core.brain import get_brain  # noqa: E402
from social_buddy.core.memory import MemoryBank  # noqa: E402
from social_buddy.core.persona import Persona  # noqa: E402
from social_buddy.core.registry import ConversationRegistry  # noqa: E402


def load_env(path: str) -> None:
    """Load a simple KEY=VALUE env file into os.environ (no external deps)."""
    if not os.path.exists(path):
        print(f"[main] config file not found: {path}", file=sys.stderr)
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


def load_persona() -> Persona:
    """Load the persona from profile.json (with seed facts), else defaults."""
    path = os.getenv("SOCIAL_BUDDY_PROFILE", "profile.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return Persona.from_dict(json.load(f))
    return Persona(name=os.getenv("SOCIAL_BUDDY_NAME", "Buddy"))


def build_registry(force_retrieval: bool = False) -> ConversationRegistry:
    persona = load_persona()
    store_dir = os.getenv("SOCIAL_BUDDY_STORE_DIR", ".")
    # force_retrieval keeps the demo fully offline (used by `simulate`
    # unless the user explicitly picked a brain backend).
    brain = None if force_retrieval else get_brain()
    registry = ConversationRegistry(
        persona=persona,
        brain=brain,
        store_dir=store_dir,
        follow_up_delay_s=float(os.getenv("SOCIAL_BUDDY_FOLLOW_UP_S", "300")),
        group_budget_per_day=int(os.getenv("SOCIAL_BUDDY_GROUP_BUDGET", "3")),
        group_min_silence_s=float(os.getenv("SOCIAL_BUDDY_GROUP_SILENCE_S", "3600")),
    )
    return registry


def main() -> None:
    ap = argparse.ArgumentParser(description="social-buddy -- an AI friend that messages you first")
    ap.add_argument("--config", default=os.getenv("SOCIAL_BUDDY_CONFIG", "config.env"),
                    help="path to a KEY=VALUE env file (default: config.env)")
    sub = ap.add_subparsers(dest="command", required=True)

    p_cli = sub.add_parser("cli", help="interactive terminal chat")
    p_cli.add_argument("--fast", action="store_true",
                       help="compress pacing so proactive messages appear in seconds")

    sub.add_parser("simulate", help="offline scripted demo of proactive behavior")
    sub.add_parser("onebot", help="connect to QQ via a OneBot v11 bridge")

    args = ap.parse_args()
    load_env(args.config)

    force_retrieval = args.command == "simulate" and not os.getenv("SOCIAL_BUDDY_BRAIN")
    registry = build_registry(force_retrieval=force_retrieval)
    if args.command == "cli":
        CliAdapter(registry.get("cli"), fast=args.fast).start()
    elif args.command == "simulate":
        SimulateAdapter(registry.get("sim")).start()
    elif args.command == "onebot":
        from social_buddy.adapters.onebot import OneBotAdapter
        OneBotAdapter(registry).start()


if __name__ == "__main__":
    main()
