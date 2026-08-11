import json
import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.middleware import _BUCKETS
from app.services import _sse_event


class HttpContractTests(unittest.TestCase):
    def setUp(self) -> None:
        _BUCKETS.clear()
        self.client = TestClient(app)

    def test_health_has_request_id(self) -> None:
        response = self.client.get("/health", headers={"X-Request-ID": "test-request"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "test-request")

    def test_metrics_are_prometheus_text(self) -> None:
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("fieldnote_http_requests_total", response.text)

    def test_registration_rate_limit(self) -> None:
        for _ in range(5):
            response = self.client.post("/auth/register", json={})
            self.assertEqual(response.status_code, 422)
        response = self.client.post("/auth/register", json={})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], 429)

    def test_sse_event_preserves_json_content(self) -> None:
        event = _sse_event("delta", {"content": "line 1\nline 2"})
        lines = event.strip().splitlines()
        self.assertEqual(lines[0], "event: delta")
        self.assertEqual(json.loads(lines[1][6:])["content"], "line 1\nline 2")
