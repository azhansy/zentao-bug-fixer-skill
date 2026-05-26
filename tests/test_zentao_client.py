import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from zentao_client import (  # noqa: E402
    ZenTaoClient,
    build_bug_comment_payload,
    is_unresolved_bug,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ZenTaoClientTests(unittest.TestCase):
    def test_request_joins_base_url_and_api_prefix(self):
        client = ZenTaoClient("https://example.com/zentao/", token="abc", api_prefix="/api.php/v1/")

        with patch("zentao_client.urlopen", return_value=FakeResponse({"ok": True})) as open_mock:
            payload = client.get("/products")

        request = open_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.com/zentao/api.php/v1/products")
        self.assertEqual(request.get_header("Token"), "abc")
        self.assertEqual(payload, {"ok": True})

    def test_is_unresolved_bug_accepts_active_and_empty_resolution_fields(self):
        self.assertTrue(is_unresolved_bug({"status": "active", "resolvedBy": "", "closedBy": ""}))
        self.assertTrue(is_unresolved_bug({"resolvedBy": None, "closedBy": None}))

    def test_is_unresolved_bug_rejects_resolved_or_closed_bugs(self):
        self.assertFalse(is_unresolved_bug({"status": "resolved", "resolvedBy": "dev", "closedBy": ""}))
        self.assertFalse(is_unresolved_bug({"status": "closed", "resolvedBy": "dev", "closedBy": "qa"}))
        self.assertFalse(is_unresolved_bug({"closedBy": "qa"}))

    def test_build_bug_comment_payload_only_contains_comment(self):
        payload = build_bug_comment_payload(
            cause="Null payload was not guarded.",
            solution="Added a defensive check before rendering.",
        )

        self.assertEqual(set(payload.keys()), {"comment"})
        self.assertIn("问题原因", payload["comment"])
        self.assertIn("解决方案", payload["comment"])
        self.assertIn("Null payload", payload["comment"])


if __name__ == "__main__":
    unittest.main()
