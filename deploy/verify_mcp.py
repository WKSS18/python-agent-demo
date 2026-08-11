"""Verify the configured MCP service from the API runtime."""

from app.mcp_client import call_tool, list_tools
from app.agent import select_mcp_tool


names = [tool.name for tool in list_tools()]
tools = list_tools()
print(f"tools={names}")
print(f"model_selection={select_mcp_tool('请查询上海现在的天气', tools)}")
print(f"calculate={call_tool('calculate', {'expression': '6*7'})}")
print(f"weather={call_tool('get_weather', {'city': 'Shanghai'})}")
print(f"stock={call_tool('get_stock_quote', {'symbol': 'sh600519'})}")
