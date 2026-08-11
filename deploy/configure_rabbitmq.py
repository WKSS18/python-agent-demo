"""Idempotently add RabbitMQ production settings without printing the password."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env.production")
    values: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for line in lines:
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value

    username = values.get("RABBITMQ_DEFAULT_USER") or "fieldnote"
    password = values.get("RABBITMQ_DEFAULT_PASS") or secrets.token_hex(24)
    updates = {
        "RABBITMQ_DEFAULT_USER": username,
        "RABBITMQ_DEFAULT_PASS": password,
        "RABBITMQ_URL": f"amqp://{username}:{password}@rabbitmq:5672/%2F",
        "RABBITMQ_DOCUMENT_QUEUE": "fieldnote.document.import",
        "RABBITMQ_DOCUMENT_DLX": "fieldnote.document.dlx",
        "DOCUMENT_MAX_ATTEMPTS": "3",
    }
    if values.get("QDRANT_API_KEY"):
        updates["QDRANT__SERVICE__API_KEY"] = values["QDRANT_API_KEY"]

    output: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")

    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"RabbitMQ settings configured for user {username}; password not displayed.")


if __name__ == "__main__":
    main()
