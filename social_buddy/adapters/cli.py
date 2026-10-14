"""CLI adapter: chat with the buddy in your terminal.

The classic demo. Type messages to talk; proactive messages appear when the
engine decides it is time (with ``--fast`` the pacing is compressed to
seconds so you can see the buddy reach out on its own).
"""

from __future__ import annotations

import sys

from .base import Adapter


class CliAdapter(Adapter):
    name = "cli"

    def __init__(self, manager, fast: bool = False):
        super().__init__(manager)
        if fast:
            manager.memory.follow_up_delay_s = 8.0
            manager.proactivity.pacing.min_silence_s = 4.0
            manager.proactivity.pacing.max_silence_s = 20.0
            manager.proactivity.pacing.budget_per_day = 100

    def send(self, text: str) -> None:
        print(f"\n  [{self.manager.persona.name}] {text}\n", flush=True)

    def start(self) -> None:
        print("=" * 60)
        print(" social-buddy -- CLI demo (type 'quit' to exit)")
        print(" The buddy will also reach out on its own when the time is right.")
        print("=" * 60)
        while True:
            proactive = self.manager.tick()
            if proactive:
                self.send(proactive)
            try:
                line = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nbye!")
                sys.exit(0)
            if line.lower() in ("quit", "exit", "q"):
                print("bye!")
                sys.exit(0)
            reply = self.manager.handle_incoming(line)
            if reply:
                self.send(reply)
