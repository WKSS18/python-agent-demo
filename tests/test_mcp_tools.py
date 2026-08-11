import unittest

from app.mcp_server import _evaluate, calculate


class McpToolTests(unittest.TestCase):
    def test_calculator_uses_safe_ast(self) -> None:
        self.assertEqual(calculate("(12 + 8) * 3")["result"], 60)

    def test_calculator_rejects_code_execution(self) -> None:
        with self.assertRaises(ValueError):
            calculate("__import__('os').system('echo unsafe')")


if __name__ == "__main__":
    unittest.main()
