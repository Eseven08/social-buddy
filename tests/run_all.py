#!/usr/bin/env python3
"""Run the whole test suite: python tests/run_all.py"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = [
    "test_memory.py",
    "test_proactivity.py",
    "test_brain.py",
    "test_conversation.py",
    "test_registry.py",
    "test_adapters.py",
]

def main() -> int:
    failed = []
    for name in TESTS:
        print(f"\n=== {name} ===")
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, name)],
            capture_output=True,
            text=True,
        )
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            failed.append(name)
    if failed:
        print(f"\nFAILED: {failed}")
        return 1
    print("\nALL TEST FILES PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
