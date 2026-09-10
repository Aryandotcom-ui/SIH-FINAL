"""Generate a bcrypt hash for an IPSAKTI_USERS entry.

    python -m backend.app.hash_password

Prompts without echoing, and prints only the hash. Deliberately does not
take the password as a command-line argument: that would put it in the
shell history and in the process list of every other user on the machine.
"""

from __future__ import annotations

import getpass
import sys

from .auth import MAX_PASSWORD_BYTES, hash_password


def main() -> int:
    password = getpass.getpass("Password: ")
    if not password:
        print("empty password", file=sys.stderr)
        return 1
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        print(
            f"password exceeds bcrypt's {MAX_PASSWORD_BYTES}-byte limit",
            file=sys.stderr,
        )
        return 1
    if password != getpass.getpass("Repeat: "):
        print("passwords do not match", file=sys.stderr)
        return 1
    print(hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
