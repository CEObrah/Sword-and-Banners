"""Non-interactive Git credential callback used by the Railway bootstrap."""

from __future__ import annotations

import os
import sys


def main() -> int:
    prompt = " ".join(sys.argv[1:]).lower()
    if "username" in prompt:
        sys.stdout.write("x-access-token")
        return 0
    if "password" in prompt:
        token = os.environ.get("SWORD_GIT_TOKEN")
        if not token or any(character in token for character in ("\x00", "\r", "\n")):
            return 1
        sys.stdout.write(token)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
