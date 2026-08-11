"""Start a local MCP server and verify discovery plus protocol tool invocation."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    env = {**os.environ, "MCP_SERVER_URL": "http://127.0.0.1:8010/mcp"}
    process = subprocess.Popen(
        [sys.executable, "-m", "app.mcp_server"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(2)
        os.environ.update(env)
        from app.mcp_client import call_tool, list_tools

        names = [tool.name for tool in list_tools()]
        required = {"get_weather", "get_stock_quote", "calculate"}
        if not required.issubset(names):
            raise RuntimeError(f"missing MCP tools: {required - set(names)}")
        result = call_tool("calculate", {"expression": "(12 + 8) * 3"})
        if '"result": 60' not in result:
            raise RuntimeError(f"unexpected MCP result: {result}")
        print(f"PASS MCP discovery={names} calculate=60")
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    main()
