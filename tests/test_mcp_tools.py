import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import agent
from app.mcp_client import McpTool
from app.mcp_server import _evaluate, calculate


class McpToolTests(unittest.TestCase):
    def test_calculator_uses_safe_ast(self) -> None:
        self.assertEqual(calculate("(12 + 8) * 3")["result"], 60)

    def test_calculator_rejects_code_execution(self) -> None:
        with self.assertRaises(ValueError):
            calculate("__import__('os').system('echo unsafe')")

    def test_weather_with_city_uses_deterministic_tool_route(self) -> None:
        tools = [McpTool("get_weather", "weather", {"type": "object"})]
        with patch(
            "app.agent.get_settings",
            return_value=SimpleNamespace(anthropic_auth_token="configured"),
        ):
            selected = agent.select_mcp_tool("请问今天北京天气如何", tools)
        self.assertEqual(selected, ("get_weather", {"city": "北京"}))

    def test_weather_without_city_requests_clarification(self) -> None:
        self.assertIsNone(agent.extract_weather_city("今天天气如何"))
        tools = [McpTool("get_weather", "weather", {"type": "object"})]
        with patch(
            "app.agent.get_settings",
            return_value=SimpleNamespace(
                anthropic_auth_token="configured", weather_default_city="上海",
            ),
        ):
            selected = agent.select_mcp_tool("今天天气如何", tools)
        self.assertEqual(selected, ("get_weather", {"city": "上海"}))

    def test_weather_prefers_browser_coordinates(self) -> None:
        tools = [McpTool("get_weather", "weather", {"type": "object"})]
        with patch(
            "app.agent.get_settings",
            return_value=SimpleNamespace(
                anthropic_auth_token="configured", weather_default_city="上海",
            ),
        ):
            selected = agent.select_mcp_tool("今天天气如何", tools, 31.23, 121.47)
        self.assertEqual(
            selected,
            ("get_weather", {"latitude": 31.23, "longitude": 121.47}),
        )


if __name__ == "__main__":
    unittest.main()
