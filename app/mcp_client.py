"""Small MCP client adapter used by the synchronous SSE service."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.config import get_settings


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict


async def _list_tools() -> list[McpTool]:
    async with httpx.AsyncClient(trust_env=False, timeout=get_settings().mcp_timeout_seconds) as client:
        async with streamable_http_client(get_settings().mcp_server_url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [McpTool(tool.name, tool.description or "", tool.inputSchema) for tool in result.tools]


async def _call_tool(name: str, arguments: dict) -> str:
    async with httpx.AsyncClient(trust_env=False, timeout=get_settings().mcp_timeout_seconds) as client:
        async with streamable_http_client(get_settings().mcp_server_url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments=arguments)
                if result.isError:
                    raise RuntimeError("MCP 工具执行失败")
                if result.structuredContent:
                    return json.dumps(result.structuredContent, ensure_ascii=False)
                return "\n".join(getattr(item, "text", "") for item in result.content).strip()


def list_tools() -> list[McpTool]:
    return asyncio.run(_list_tools())


def call_tool(name: str, arguments: dict) -> str:
    return asyncio.run(_call_tool(name, arguments))
