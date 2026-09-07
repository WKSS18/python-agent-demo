"""Fieldnote MCP server exposing read-only public-information tools."""

from __future__ import annotations

import ast
import operator
import re
from datetime import UTC, datetime

import httpx
from mcp.server.fastmcp import FastMCP


mcp = FastMCP(
    "Fieldnote Tools",
    instructions="Read-only weather, market quote and calculation tools.",
    host="0.0.0.0",
    port=8010,
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def get_weather(
    city: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict:
    """Get current weather by city or the user's latitude and longitude."""
    with httpx.Client(timeout=8) as client:
        if latitude is not None and longitude is not None:
            location = {"name": "当前位置", "latitude": latitude, "longitude": longitude}
        else:
            if not city.strip():
                raise ValueError("必须提供城市或经纬度")
            place = client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "zh", "format": "json"},
            ).raise_for_status().json()
            results = place.get("results") or []
            if not results:
                raise ValueError(f"找不到城市：{city}")
            location = results[0]
        forecast = client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
        ).raise_for_status().json()
    return {
        "city": location["name"],
        "country": location.get("country"),
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        **forecast["current"],
    }


@mcp.tool()
def get_stock_quote(symbol: str) -> dict:
    """Get a delayed stock quote. Symbols: sh600519, sz000001, hk00700, usAAPL."""
    normalized = re.sub(r"[^A-Za-z0-9]", "", symbol)
    if not re.fullmatch(r"(?i)(sh|sz|hk|us)[A-Z0-9]{1,10}", normalized):
        raise ValueError("股票代码格式应为 sh600519、sz000001、hk00700 或 usAAPL")
    response = httpx.get(
        f"https://qt.gtimg.cn/q={normalized}",
        headers={"Referer": "https://finance.qq.com/"},
        timeout=8,
    )
    response.raise_for_status()
    fields = response.content.decode("gbk", errors="replace").split("~")
    if len(fields) < 46 or not fields[1]:
        raise ValueError(f"未查询到股票：{symbol}")
    return {
        "symbol": normalized,
        "name": fields[1],
        "price": fields[3],
        "previous_close": fields[4],
        "open": fields[5],
        "change": fields[31],
        "change_percent": fields[32],
        "high": fields[33],
        "low": fields[34],
        "quote_time": fields[30],
        "source": "腾讯行情（可能延迟）",
    }


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_evaluate(node.operand))
    raise ValueError("只支持数字、括号和 + - * / // % **")


@mcp.tool()
def calculate(expression: str) -> dict:
    """Safely calculate an arithmetic expression without executing code."""
    if len(expression) > 200:
        raise ValueError("表达式过长")
    value = _evaluate(ast.parse(expression, mode="eval"))
    if abs(float(value)) > 1e100:
        raise ValueError("计算结果过大")
    return {"expression": expression, "result": value, "calculated_at": datetime.now(UTC).isoformat()}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
