"""Merge only OSS-related values into a production env file without printing secrets."""

from __future__ import annotations

import os
import sys
from pathlib import Path


KEYS = (
    "OSS_ACCESS_KEY_ID",
    "OSS_ACCESS_KEY_SECRET",
    "OSS_ENDPOINT",
    "OSS_BUCKET",
    "OSS_OBJECT_PREFIX",
    "OSS_SIGNED_URL_EXPIRE_SECONDS",
)


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def main() -> None:
    source, target = map(Path, sys.argv[1:3])
    incoming = read_env(source)
    required = KEYS[:4]
    missing = [key for key in required if not incoming.get(key)]
    if missing:
        raise SystemExit(f"missing required OSS settings: {', '.join(missing)}")

    values = {key: incoming[key] for key in KEYS if incoming.get(key)}
    values["ATTACHMENT_STORAGE_BACKEND"] = "oss"
    lines = target.read_text(encoding="utf-8").splitlines()
    written: set[str] = set()
    output: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in values:
            output.append(f"{key}={values[key]}")
            written.add(key)
        else:
            output.append(line)
    for key, value in values.items():
        if key not in written:
            output.append(f"{key}={value}")

    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    print("OSS settings merged successfully")


if __name__ == "__main__":
    main()
