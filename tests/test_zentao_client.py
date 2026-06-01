import json
import io
import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from zentao_client import (  # noqa: E402
    _build_client,
    ZenTaoClient,
    build_bug_comment_payload,
    is_code_bug,
    is_unresolved_bug,
    repairable_bugs,
    validate_bug_type,
)
import zentao_client as zentao_client_module  # noqa: E402


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


class FakeRawResponse:
    def __init__(self, body, status=200, url="https://example.com/zentao/action-comment-bug-6025.json"):
        self.body = body
        self.status = status
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body.encode("utf-8")

    def geturl(self):
        return self.url


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

    def test_is_code_bug_accepts_code_issue_type_values(self):
        self.assertTrue(is_code_bug({"type": "codeerror"}))
        self.assertTrue(is_code_bug({"type": "代码问题"}))
        self.assertTrue(is_code_bug({"type": {"name": "代码错误"}}))

    def test_is_code_bug_rejects_product_logic_and_empty_types(self):
        self.assertFalse(is_code_bug({"type": "产品逻辑"}))
        self.assertFalse(is_code_bug({"type": {"name": "需求问题"}}))
        self.assertFalse(is_code_bug({"title": "缺少 type 字段"}))

    def test_repairable_bugs_only_returns_unresolved_code_bugs(self):
        bugs = [
            {"id": 1, "status": "active", "type": "代码问题"},
            {"id": 2, "status": "active", "type": "产品逻辑"},
            {"id": 3, "status": "resolved", "type": "codeerror", "resolvedBy": "dev"},
        ]

        self.assertEqual(repairable_bugs(bugs), [bugs[0]])

    def test_build_bug_comment_payload_only_contains_comment(self):
        payload = build_bug_comment_payload(
            cause="消息附件数组只读取了第一项。",
            solution="遍历全部附件并逐条生成消息内容。",
        )

        self.assertEqual(set(payload.keys()), {"comment"})
        self.assertIn("问题原因", payload["comment"])
        self.assertIn("解决方案", payload["comment"])
        self.assertIn("消息附件数组", payload["comment"])

    def test_comment_bug_posts_to_action_comment_endpoint(self):
        client = ZenTaoClient("https://example.com/zentao", token="abc")

        with (
            patch.object(client, "ensure_web_session") as session_mock,
            patch.object(client, "post_form", return_value={"status": "success", "data": 123}) as post_mock,
        ):
            payload = client.comment_bug(
                6025,
                "消息附件数组只读取了第一项。",
                "遍历全部附件并逐条生成消息内容。",
            )

        session_mock.assert_called_once()
        post_mock.assert_called_once_with(
            "/action-comment-bug-6025.json",
            {"comment": "问题原因：消息附件数组只读取了第一项。\n\n解决方案：遍历全部附件并逐条生成消息内容。"},
            allow_non_json_success=True,
        )
        self.assertEqual(payload, {"status": "success", "data": 123})

    def test_comment_bug_treats_non_json_http_success_as_success(self):
        client = ZenTaoClient("https://example.com/zentao", token="abc", account="alice", password="secret")
        client.session_name = "zentaosid"
        client.session_id = "session-123"

        with patch("zentao_client.urlopen", return_value=FakeRawResponse("<html>saved</html>")):
            payload = client.comment_bug(6025, "测试原因", "测试方案")

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["format"], "raw")
        self.assertEqual(payload["statusCode"], 200)

    def test_comment_bug_uses_default_resolved_build_when_resolving(self):
        client = ZenTaoClient(
            "https://example.com/zentao",
            token="abc",
            account="alice",
            password="secret",
            resolve_bug_after_comment=True,
        )
        client.session_name = "zentaosid"
        client.session_id = "session-123"

        with (
            patch.object(client, "ensure_web_session") as session_mock,
            patch.object(client, "post_form", return_value={"status": "success", "format": "raw"}),
            patch.object(client, "post", return_value={"status": "success"}) as resolve_mock,
        ):
            payload = client.comment_bug(6025, "测试原因", "测试方案")

        session_mock.assert_called_once()
        resolve_mock.assert_called_once_with("/bugs/6025/resolve", {"resolution": "fixed", "resolvedBuild": "主干"})
        self.assertEqual(payload["resolve"], {"status": "success"})

    def test_comment_bug_can_resolve_after_comment_when_enabled_with_build(self):
        client = ZenTaoClient(
            "https://example.com/zentao",
            token="abc",
            account="alice",
            password="secret",
            resolve_bug_after_comment=True,
            resolved_build="build-20260529",
        )
        client.session_name = "zentaosid"
        client.session_id = "session-123"

        with (
            patch.object(client, "ensure_web_session") as session_mock,
            patch.object(client, "post_form", return_value={"status": "success", "format": "raw"}) as comment_mock,
            patch.object(client, "post", return_value={"status": "success", "id": 6025, "statusText": "resolved"}) as resolve_mock,
        ):
            payload = client.comment_bug(6025, "测试原因", "测试方案")

        session_mock.assert_called_once()
        comment_mock.assert_called_once_with(
            "/action-comment-bug-6025.json",
            {"comment": "问题原因：测试原因\n\n解决方案：测试方案"},
            allow_non_json_success=True,
        )
        resolve_mock.assert_called_once_with(
            "/bugs/6025/resolve",
            {"resolution": "fixed", "resolvedBuild": "build-20260529"},
        )
        self.assertEqual(
            payload,
            {
                "comment": {"status": "success", "format": "raw"},
                "resolve": {"status": "success", "id": 6025, "statusText": "resolved"},
            },
        )

    def test_main_resolve_subcommand_calls_resolve_bug(self):
        with patch.object(zentao_client_module, "_build_client") as build_client_mock:
            client = ZenTaoClient("https://example.com/zentao", token="abc", resolved_build="主干")
            build_client_mock.return_value = client

            with patch.object(client, "resolve_bug", return_value={"status": "success", "id": 6025}) as resolve_mock:
                with patch("sys.stdout", new=io.StringIO()):
                    exit_code = zentao_client_module.main(
                        [
                            "--base-url",
                            "https://example.com/zentao",
                            "--token",
                            "abc",
                            "resolve",
                            "6025",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        resolve_mock.assert_called_once_with(6025, resolution="fixed", resolved_build=None)

    def test_update_bug_type_puts_type_field(self):
        client = ZenTaoClient("https://example.com/zentao", token="abc")

        with patch.object(client, "put", return_value={"status": "success", "id": 6025}) as put_mock:
            payload = client.update_bug(6025, bug_type="others")

        put_mock.assert_called_once_with("/bugs/6025", {"type": "others"})
        self.assertEqual(payload, {"status": "success", "id": 6025})

    def test_validate_bug_type_accepts_chinese_code_issue_label(self):
        self.assertEqual(validate_bug_type("代码问题"), "codeerror")

    def test_validate_bug_type_rejects_unknown_values(self):
        with self.assertRaisesRegex(ValueError, "Unsupported ZenTao bug type"):
            validate_bug_type("需求问题")

    def test_main_bug_update_subcommand_calls_update_bug(self):
        with patch.object(zentao_client_module, "_build_client") as build_client_mock:
            client = ZenTaoClient("https://example.com/zentao", token="abc")
            build_client_mock.return_value = client

            with patch.object(client, "update_bug", return_value={"status": "success", "id": 6025}) as update_mock:
                with patch("sys.stdout", new=io.StringIO()):
                    exit_code = zentao_client_module.main(
                        [
                            "--base-url",
                            "https://example.com/zentao",
                            "--token",
                            "abc",
                            "bug-update",
                            "6025",
                            "--type",
                            "others",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        update_mock.assert_called_once_with(6025, bug_type="others")

    def test_from_env_reads_resolve_bug_after_comment_flag(self):
        with patch.dict(
            os.environ,
            {
                "ZENTAO_BASE_URL": "https://example.com/zentao",
                "ZENTAO_RESOLVE_BUG_AFTER_COMMENT": "1",
            },
            clear=True,
        ):
            client = ZenTaoClient.from_env()

        self.assertTrue(client.resolve_bug_after_comment)

    def test_from_env_loads_values_from_default_env_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        'export ZENTAO_BASE_URL="https://example.com/zentao"',
                        "ZENTAO_ACCOUNT=alice",
                        "ZENTAO_PASSWORD=secret",
                        "ZENTAO_TOKEN=token-123",
                        "ZENTAO_RESOLVE_BUG_AFTER_COMMENT=1",
                    ]
                ),
                encoding="utf-8",
            )

            with (
                patch.dict(os.environ, {}, clear=True),
                patch("zentao_client._zentao_env_file_path", return_value=env_file),
            ):
                client = ZenTaoClient.from_env()

        self.assertEqual(client.base_url, "https://example.com/zentao")
        self.assertEqual(client.account, "alice")
        self.assertEqual(client.password, "secret")
        self.assertEqual(client.token, "token-123")
        self.assertTrue(client.resolve_bug_after_comment)

    def test_build_client_prefers_cli_resolve_flag_over_env(self):
        args = type(
            "Args",
            (),
            {
                "base_url": "https://example.com/zentao",
                "api_prefix": None,
                "token": "abc",
                "account": None,
                "password": None,
                "resolve_bug_after_comment": False,
                "resolved_build": None,
            },
        )()

        with patch.dict(os.environ, {"ZENTAO_RESOLVE_BUG_AFTER_COMMENT": "1"}, clear=True):
            client = _build_client(args)

        self.assertFalse(client.resolve_bug_after_comment)

    def test_build_client_defaults_resolved_build_to_trunk(self):
        args = type(
            "Args",
            (),
            {
                "base_url": "https://example.com/zentao",
                "api_prefix": None,
                "token": "abc",
                "account": None,
                "password": None,
                "resolve_bug_after_comment": None,
                "resolved_build": None,
            },
        )()

        with patch.dict(os.environ, {}, clear=True):
            client = _build_client(args)

        self.assertEqual(client.resolved_build, "主干")

    def test_build_client_reads_resolved_build_from_env(self):
        args = type(
            "Args",
            (),
            {
                "base_url": "https://example.com/zentao",
                "api_prefix": None,
                "token": "abc",
                "account": None,
                "password": None,
                "resolve_bug_after_comment": None,
                "resolved_build": None,
            },
        )()

        with patch.dict(os.environ, {"ZENTAO_RESOLVED_BUILD": "build-20260529"}, clear=True):
            client = _build_client(args)

        self.assertEqual(client.resolved_build, "build-20260529")

    def test_ensure_web_session_logs_in_with_json_api_session_cookie(self):
        client = ZenTaoClient("https://example.com/zentao", account="alice", password="secret")
        responses = [
            {
                "status": "success",
                "data": json.dumps({"sessionName": "zentaosid", "sessionID": "session-123"}),
            },
            {
                "status": "success",
                "user": {"token": "session-123"},
            },
        ]

        with patch.object(client, "request_form", side_effect=responses) as form_mock:
            client.ensure_web_session()

        self.assertEqual(client.session_name, "zentaosid")
        self.assertEqual(client.session_id, "session-123")
        self.assertEqual(
            [call.args for call in form_mock.call_args_list],
            [
                ("GET", "/api-getSessionID.json", None, None),
                ("POST", "/user-login.json", {"account": "alice", "password": "secret"}, {"zentaosid": "session-123"}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
