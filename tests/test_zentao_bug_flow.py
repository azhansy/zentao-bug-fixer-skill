import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from zentao_bug_flow import (  # noqa: E402
    bugs_for_assignee,
    format_assignee_summary,
    format_bug_summary,
    format_product_summary,
    load_repairable_bugs,
    parse_assignee_selection,
)


class ZenTaoBugFlowTests(unittest.TestCase):
    def test_format_product_summary_shows_numbered_products(self):
        products = [{"id": 8, "name": "Loopin Tasks"}, {"id": 7, "name": "服装定制系统"}]

        summary = format_product_summary(products)

        self.assertIn("1. [8] Loopin Tasks", summary)
        self.assertIn("2. [7] 服装定制系统", summary)

    def test_format_bug_summary_includes_priority_and_steps_preview(self):
        bug = {
            "id": 6025,
            "title": "一次发送两个视频只看到一个",
            "pri": 1,
            "severity": 2,
            "steps": "<p>1. 打开会话</p><p>2. 发送两个视频</p>",
        }

        summary = format_bug_summary([bug])

        self.assertIn("#6025", summary)
        self.assertIn("P1", summary)
        self.assertIn("S2", summary)
        self.assertIn("打开会话", summary)

    def test_format_assignee_summary_groups_unresolved_bugs(self):
        bugs = [
            {"id": 10, "assignedTo": {"account": "alice", "realname": "Alice"}},
            {"id": 20, "assignedTo": {"account": "alice", "realname": "Alice"}},
            {"id": 30, "assignedTo": "bob"},
        ]

        summary = format_assignee_summary(bugs)

        self.assertIn("1. alice / Alice (2 bugs)", summary)
        self.assertIn("2. bob (1 bug)", summary)

    def test_parse_assignee_selection_supports_index_account_and_name(self):
        bugs = [
            {"id": 10, "assignedTo": {"account": "alice", "realname": "Alice"}},
            {"id": 20, "assignedTo": "bob"},
        ]

        self.assertEqual(parse_assignee_selection("1", bugs), "alice")
        self.assertEqual(parse_assignee_selection("bob", bugs), "bob")
        self.assertEqual(parse_assignee_selection("Alice", bugs), "alice")

    def test_bugs_for_assignee_returns_all_matching_unresolved_bugs(self):
        bugs = [
            {"id": 10, "assignedTo": {"account": "alice", "realname": "Alice"}},
            {"id": 20, "assignedTo": "bob"},
            {"id": 30, "assignedTo": {"account": "alice", "realname": "Alice"}},
        ]

        self.assertEqual(bugs_for_assignee("alice", bugs), [bugs[0], bugs[2]])

    def test_load_repairable_bugs_filters_to_unresolved_code_bugs(self):
        class Client:
            def product_bugs(self, product_id):
                self.product_id = product_id
                return [
                    {"id": 10, "status": "active", "type": "产品逻辑"},
                    {"id": 20, "status": "active", "type": "代码问题"},
                    {"id": 30, "status": "resolved", "type": "codeerror", "resolvedBy": "dev"},
                ]

        client = Client()

        self.assertEqual(load_repairable_bugs(client, 8), [{"id": 20, "status": "active", "type": "代码问题"}])
        self.assertEqual(client.product_id, 8)


if __name__ == "__main__":
    unittest.main()
