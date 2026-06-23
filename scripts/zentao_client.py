#!/usr/bin/env python3
"""Small ZenTao REST client for Codex skills.

The module intentionally uses only the Python standard library so the skill can
be copied into any business repository without dependency installation.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_API_PREFIX = "/api.php/v1"
DEFAULT_TESTCASE_API_PREFIX = "/api.php/v2"
DEFAULT_RESOLVE_BUG_AFTER_COMMENT = False
DEFAULT_RESOLVED_BUILD = "主干"
BUG_TYPE_VALUES = {
    "codeerror",
    "config",
    "install",
    "security",
    "performance",
    "standard",
    "automation",
    "designdefect",
    "others",
}
BUG_TYPE_ALIASES = {
    "代码问题": "codeerror",
    "代码错误": "codeerror",
    "code": "codeerror",
    "code error": "codeerror",
    "codeissue": "codeerror",
    "code issue": "codeerror",
    "设计缺陷": "designdefect",
    "设计问题": "designdefect",
    "其他": "others",
}
CODE_BUG_TYPE_VALUES = {
    "code",
    "codeerror",
    "code error",
    "codeissue",
    "code issue",
    "代码问题",
    "代码错误",
}
CODE_BUG_TYPE_FIELDS = ("type", "bugType", "typeName", "typeLabel", "Bug类型")


class ZenTaoError(RuntimeError):
    """Raised for ZenTao API and configuration failures."""


def _strip_join(left: str, right: str) -> str:
    return f"{left.rstrip('/')}/{right.strip('/')}"


def _json_loads(data: bytes) -> Any:
    if not data:
        return {}
    return json.loads(data.decode("utf-8"))


@dataclass
class ZenTaoClient:
    base_url: str
    token: Optional[str] = None
    api_prefix: str = DEFAULT_API_PREFIX
    testcase_api_prefix: str = DEFAULT_TESTCASE_API_PREFIX
    timeout: int = 30
    account: Optional[str] = None
    password: Optional[str] = None
    session_name: Optional[str] = None
    session_id: Optional[str] = None
    resolve_bug_after_comment: bool = DEFAULT_RESOLVE_BUG_AFTER_COMMENT
    resolved_build: Optional[str] = DEFAULT_RESOLVED_BUILD

    @classmethod
    def from_env(cls) -> "ZenTaoClient":
        _load_zentao_env()
        base_url = os.getenv("ZENTAO_BASE_URL")
        if not base_url:
            raise ZenTaoError("Missing ZENTAO_BASE_URL.")
        return cls(
            base_url=base_url,
            token=os.getenv("ZENTAO_TOKEN"),
            api_prefix=os.getenv("ZENTAO_API_PREFIX", DEFAULT_API_PREFIX),
            testcase_api_prefix=os.getenv("ZENTAO_TESTCASE_API_PREFIX", DEFAULT_TESTCASE_API_PREFIX),
            resolve_bug_after_comment=_env_bool(
                "ZENTAO_RESOLVE_BUG_AFTER_COMMENT",
                DEFAULT_RESOLVE_BUG_AFTER_COMMENT,
            ),
            account=os.getenv("ZENTAO_ACCOUNT"),
            password=os.getenv("ZENTAO_PASSWORD"),
            resolved_build=_clean_optional_string(os.getenv("ZENTAO_RESOLVED_BUILD")) or DEFAULT_RESOLVED_BUILD,
        )

    def url(
        self,
        path: str,
        query: Optional[Dict[str, Any]] = None,
        api_prefix: Optional[str] = None,
    ) -> str:
        full = _strip_join(_strip_join(self.base_url, api_prefix or self.api_prefix), path)
        clean_query = {
            key: value
            for key, value in (query or {}).items()
            if value is not None and value != ""
        }
        if clean_query:
            full = f"{full}?{urlencode(clean_query)}"
        return full

    def web_url(self, path: str) -> str:
        return _strip_join(self.base_url, path)

    def request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
        api_prefix: Optional[str] = None,
    ) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Token"] = self.token
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(self.url(path, query, api_prefix=api_prefix), data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return _json_loads(response.read())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ZenTaoError(f"ZenTao HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ZenTaoError(f"ZenTao request failed: {exc.reason}") from exc

    def request_form(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, str]] = None,
        allow_non_json_success: bool = False,
    ) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
        if payload is not None:
            body = urlencode(payload).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = Request(self.web_url(path), data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                response_body = response.read()
                try:
                    return _json_loads(response_body)
                except json.JSONDecodeError:
                    if not allow_non_json_success:
                        raise
                    return {
                        "status": "success",
                        "format": "raw",
                        "statusCode": getattr(response, "status", None),
                        "url": response.geturl() if hasattr(response, "geturl") else request.full_url,
                    }
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ZenTaoError(f"ZenTao HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ZenTaoError(f"ZenTao request failed: {exc.reason}") from exc

    def get(self, path: str, query: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("GET", path, query=query)

    def post(self, path: str, payload: Dict[str, Any], api_prefix: Optional[str] = None) -> Any:
        return self.request("POST", path, payload=payload, api_prefix=api_prefix)

    def put(self, path: str, payload: Dict[str, Any]) -> Any:
        return self.request("PUT", path, payload=payload)

    def resolve_bug(self, bug_id: int, resolution: str = "fixed", resolved_build: Optional[str] = None) -> Any:
        payload = {"resolution": resolution}
        build = _clean_optional_string(resolved_build) or _clean_optional_string(self.resolved_build)
        if build:
            payload["resolvedBuild"] = build
        data = self.post(f"/bugs/{bug_id}/resolve", payload)
        if isinstance(data, dict) and data.get("status") == "success":
            return data
        raise ZenTaoError(f"ZenTao resolve failed: {data}")

    def login(self, account: str, password: str) -> str:
        data = self.post("/tokens", {"account": account, "password": password})
        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise ZenTaoError("Login succeeded but response did not contain token.")
        self.token = token
        self.account = account
        self.password = password
        return token

    def ensure_web_session(self) -> None:
        if self.session_name and self.session_id:
            return
        if not self.account or not self.password:
            raise ZenTaoError("Set ZENTAO_ACCOUNT and ZENTAO_PASSWORD to add ZenTao comments.")

        session_data = self.request_form("GET", "/api-getSessionID.json", None, None)
        session = _response_data_object(session_data)
        session_name = session.get("sessionName") if isinstance(session, dict) else None
        session_id = session.get("sessionID") if isinstance(session, dict) else None
        if not session_name or not session_id:
            raise ZenTaoError("Could not obtain ZenTao web session.")

        login_data = self.request_form(
            "POST",
            "/user-login.json",
            {"account": self.account, "password": self.password},
            {str(session_name): str(session_id)},
        )
        if not isinstance(login_data, dict) or login_data.get("status") != "success":
            raise ZenTaoError(f"ZenTao web login failed: {login_data}")

        self.session_name = str(session_name)
        self.session_id = str(session_id)

    def post_form(self, path: str, payload: Dict[str, Any], allow_non_json_success: bool = False) -> Any:
        return self.request_form("POST", path, payload, self._session_cookies(), allow_non_json_success)

    def _session_cookies(self) -> Dict[str, str]:
        if not self.session_name or not self.session_id:
            raise ZenTaoError("ZenTao web session has not been initialized.")
        return {self.session_name: self.session_id}

    def products(self) -> List[Dict[str, Any]]:
        data = self.get("/products")
        if isinstance(data, dict):
            for key in ("products", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
        if isinstance(data, list):
            return data
        raise ZenTaoError("Could not find product list in response.")

    def product_bugs(self, product_id: int, page: Optional[int] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        data = self.get(f"/products/{product_id}/bugs", query={"page": page, "limit": limit})
        if isinstance(data, dict) and isinstance(data.get("bugs"), list):
            return data["bugs"]
        raise ZenTaoError("Could not find bugs list in response.")

    def bug(self, bug_id: int) -> Dict[str, Any]:
        data = self.get(f"/bugs/{bug_id}")
        if isinstance(data, dict):
            if isinstance(data.get("bug"), dict):
                return data["bug"]
            return data
        raise ZenTaoError("Could not find bug detail in response.")

    def update_bug(self, bug_id: int, bug_type: Optional[str] = None) -> Any:
        payload: Dict[str, Any] = {}
        if bug_type is not None:
            payload["type"] = validate_bug_type(bug_type)
        if not payload:
            raise ZenTaoError("No bug fields were provided for update.")

        data = self.put(f"/bugs/{bug_id}", payload)
        if isinstance(data, dict) and data.get("status") == "success":
            return data
        raise ZenTaoError(f"ZenTao bug update failed: {data}")

    def comment_bug(self, bug_id: int, cause: str, solution: str) -> Any:
        payload = build_bug_comment_payload(cause=cause, solution=solution)
        self.ensure_web_session()
        data = self.post_form(f"/action-comment-bug-{bug_id}.json", payload, allow_non_json_success=True)
        if isinstance(data, dict) and data.get("status") == "success":
            if self.resolve_bug_after_comment:
                resolve_data = self.resolve_bug(bug_id)
                return {"comment": data, "resolve": resolve_data}
            return data
        raise ZenTaoError(f"ZenTao comment failed: {data}")

    def create_test_case(self, test_case: Dict[str, Any]) -> Any:
        payload = build_test_case_payload(test_case)
        data = self.post("/testcases", payload, api_prefix=self.testcase_api_prefix)
        if isinstance(data, dict) and data.get("status") == "success":
            return data
        if data == {}:
            return self.create_test_case_web_form(payload)
        raise ZenTaoError(f"ZenTao testcase create failed: {data}")

    def create_test_case_web_form(self, test_case: Dict[str, Any]) -> Any:
        payload = build_test_case_web_form_payload(test_case)
        product_id = str(test_case["productID"])
        module_id = str(test_case.get("module", 0) or 0)
        self.ensure_web_session()
        data = self.post_form(
            f"/testcase-create-{product_id}-all-{module_id}.json",
            payload,
            allow_non_json_success=True,
        )
        if isinstance(data, dict) and (data.get("result") == "success" or data.get("status") == "success"):
            return data
        raise ZenTaoError(f"ZenTao testcase web-form create failed: {data}")


def is_unresolved_bug(bug: Dict[str, Any]) -> bool:
    status = str(bug.get("status") or "").lower()
    closed_by = bug.get("closedBy")
    resolved_by = bug.get("resolvedBy")

    if status == "closed" or closed_by:
        return False
    if status in {"resolved", "done"} or resolved_by:
        return False
    return True


def unresolved_bugs(bugs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [bug for bug in bugs if is_unresolved_bug(bug)]


def is_code_bug(bug: Dict[str, Any]) -> bool:
    for field in CODE_BUG_TYPE_FIELDS:
        if _type_value_is_code_bug(bug.get(field)):
            return True
    return False


def repairable_bugs(bugs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [bug for bug in bugs if is_unresolved_bug(bug) and is_code_bug(bug)]


def _type_value_is_code_bug(value: Any) -> bool:
    for text in _type_text_values(value):
        normalized = _normalize_type_text(text)
        compact = normalized.replace(" ", "")
        if normalized in CODE_BUG_TYPE_VALUES or compact in CODE_BUG_TYPE_VALUES:
            return True
    return False


def _type_text_values(value: Any) -> Iterator[str]:
    if value in (None, ""):
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _type_text_values(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _type_text_values(item)
        return
    yield str(value)


def _normalize_type_text(value: str) -> str:
    text = value.strip().casefold()
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.split())


def bug_sort_key(bug: Dict[str, Any]) -> tuple:
    severity = _int_or_default(bug.get("severity"), 99)
    priority = _int_or_default(bug.get("pri"), 99)
    bug_id = _int_or_default(bug.get("id"), 0)
    return (priority or 99, severity or 99, bug_id)


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_bug_comment_payload(cause: str, solution: str) -> Dict[str, Any]:
    clean_cause = cause.strip()
    clean_solution = solution.strip()
    comment = (
        "问题原因：\n"
        f"{clean_cause}\n\n"
        "解决方案：\n"
        f"{clean_solution}\n\n"
        "---------\n"
        "通过 &lt;zentao-bug-fixer&gt; Skill 自动完成问题分析与修复。"
    )
    return {"comment": comment}


def load_test_case_batch(path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        defaults: Dict[str, Any] = {}
        cases = raw
    elif isinstance(raw, dict):
        defaults = _ensure_dict(raw.get("defaults") or {}, "defaults")
        cases = raw.get("cases")
    else:
        raise ValueError("Test case file must contain a JSON array or an object with a cases array.")

    if not isinstance(cases, list):
        raise ValueError("Test case file must contain a cases array.")
    if not cases:
        raise ValueError("Test case file does not contain any test cases.")

    return [build_test_case_payload(_ensure_dict(test_case, f"cases[{index}]"), defaults) for index, test_case in enumerate(cases)]


def build_test_case_payload(test_case: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    merged = dict(defaults or {})
    merged.update(test_case)

    payload: Dict[str, Any] = {}
    for key in (
        "productID",
        "title",
        "module",
        "story",
        "pri",
        "type",
        "precondition",
        "project",
        "execution",
    ):
        value = _case_value(merged, key)
        if value not in (None, ""):
            payload[key] = value

    product_id = _first_present(merged, "productID", "productId", "product_id", "product")
    if product_id not in (None, ""):
        payload["productID"] = product_id

    title = _case_value(merged, "title")
    if title not in (None, ""):
        payload["title"] = title

    if "productID" not in payload:
        raise ValueError("Test case is missing required field productID.")
    if "title" not in payload:
        raise ValueError("Test case is missing required field title.")

    steps, expects, step_types = _normalize_test_case_steps(merged)
    if steps:
        payload["steps"] = steps
        payload["expects"] = expects
        payload["stepType"] = step_types

    return payload


def build_test_case_web_form_payload(test_case: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product": str(test_case["productID"]),
        "module": str(test_case.get("module", 0) or 0),
        "story": str(test_case.get("story", 0) or 0),
        "scene": str(test_case.get("scene", 0) or 0),
        "type": str(test_case.get("type", "feature") or "feature"),
        "title": str(test_case["title"]),
        "pri": str(test_case.get("pri", 3) or 3),
        "precondition": str(test_case.get("precondition", "") or ""),
        "keywords": str(test_case.get("keywords", "") or ""),
    }

    steps = test_case.get("steps") or []
    expects = test_case.get("expects") or ["" for _ in steps]
    step_types = test_case.get("stepType") or ["step" for _ in steps]
    for index, step in enumerate(steps, start=1):
        payload[f"steps[{index}]"] = str(step)
        payload[f"expects[{index}]"] = str(expects[index - 1] if index - 1 < len(expects) else "")
        payload[f"stepType[{index}]"] = str(step_types[index - 1] if index - 1 < len(step_types) else "step")

    return payload


def _normalize_test_case_steps(test_case: Dict[str, Any]) -> tuple:
    raw_steps = test_case.get("steps")
    if raw_steps in (None, ""):
        return ([], [], [])
    if not isinstance(raw_steps, list):
        raise ValueError("Test case steps must be an array.")

    steps: List[str] = []
    expects: List[str] = []
    step_types: List[str] = []

    if raw_steps and all(isinstance(item, dict) for item in raw_steps):
        for index, item in enumerate(raw_steps):
            step = _first_present(item, "step", "action", "desc", "description", "content", "name")
            if step in (None, ""):
                raise ValueError(f"Test case step {index + 1} is missing step text.")
            steps.append(str(step))
            expects.append(str(_first_present(item, "expect", "expected", "result") or ""))
            step_types.append(str(_first_present(item, "type", "stepType") or "step"))
        return (steps, expects, step_types)

    steps = [str(item) for item in raw_steps]
    raw_expects = test_case.get("expects", test_case.get("expected", []))
    if raw_expects in (None, "") or raw_expects == []:
        expects = ["" for _ in steps]
    elif isinstance(raw_expects, list):
        expects = [str(item) for item in raw_expects]
    else:
        raise ValueError("Test case expects must be an array when steps are an array.")
    if len(expects) != len(steps):
        raise ValueError("Test case expects length must match steps length.")

    raw_step_types = test_case.get("stepType", test_case.get("stepTypes", []))
    if raw_step_types in (None, "") or raw_step_types == []:
        step_types = ["step" for _ in steps]
    elif isinstance(raw_step_types, list):
        step_types = [str(item) for item in raw_step_types]
    else:
        raise ValueError("Test case stepType must be an array.")
    if len(step_types) != len(steps):
        raise ValueError("Test case stepType length must match steps length.")

    return (steps, expects, step_types)


def upload_test_case_batch(
    client: ZenTaoClient,
    cases: List[Dict[str, Any]],
    continue_on_error: bool = False,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    failed = 0
    for index, test_case in enumerate(cases):
        title = str(test_case.get("title") or "")
        try:
            response = client.create_test_case(test_case)
        except Exception as exc:
            failed += 1
            if not continue_on_error:
                raise
            results.append({"index": index, "title": title, "status": "fail", "error": str(exc)})
            continue
        results.append({"index": index, "title": title, "status": "success", "response": response})

    return {
        "status": "success" if failed == 0 else "partial",
        "created": len(cases) - failed,
        "failed": failed,
        "results": results,
    }


def _ensure_dict(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object.")
    return value


def _case_value(test_case: Dict[str, Any], key: str) -> Any:
    return test_case.get(key)


def _first_present(values: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in values:
            return values[key]
    return None


def validate_bug_type(value: str) -> str:
    normalized = _normalize_type_text(value)
    compact = normalized.replace(" ", "")
    if normalized in BUG_TYPE_VALUES:
        return normalized
    if compact in BUG_TYPE_VALUES:
        return compact
    if value.strip() in BUG_TYPE_ALIASES:
        return BUG_TYPE_ALIASES[value.strip()]
    if normalized in BUG_TYPE_ALIASES:
        return BUG_TYPE_ALIASES[normalized]
    if compact in BUG_TYPE_ALIASES:
        return BUG_TYPE_ALIASES[compact]
    allowed = ", ".join(sorted(BUG_TYPE_VALUES))
    raise ValueError(f"Unsupported ZenTao bug type: {value}. Allowed values: {allowed}")


def _load_zentao_env() -> None:
    for key, value in _read_env_file(_zentao_env_file_path()).items():
        os.environ.setdefault(key, value)


def _zentao_env_file_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".env"


def _read_env_file(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}

    env: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        raw_value = raw_value.strip()
        if raw_value == "":
            env[key] = ""
            continue
        try:
            parsed = shlex.split(raw_value, posix=True)
        except ValueError:
            continue
        value = " ".join(parsed) if parsed else ""
        env[key] = value
    return env


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ZenTaoError(f"Invalid boolean value for {name}: {raw}")


def _clean_optional_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    clean = value.strip()
    return clean or None


def _response_data_object(response: Any) -> Any:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _build_client(args: argparse.Namespace) -> ZenTaoClient:
    _load_zentao_env()
    env_resolve_flag = _env_bool(
        "ZENTAO_RESOLVE_BUG_AFTER_COMMENT",
        DEFAULT_RESOLVE_BUG_AFTER_COMMENT,
    )
    resolve_bug_after_comment = (
        env_resolve_flag
        if getattr(args, "resolve_bug_after_comment", None) is None
        else bool(args.resolve_bug_after_comment)
    )
    client = ZenTaoClient(
        base_url=args.base_url or os.getenv("ZENTAO_BASE_URL", ""),
        token=args.token or os.getenv("ZENTAO_TOKEN"),
        api_prefix=args.api_prefix or os.getenv("ZENTAO_API_PREFIX", DEFAULT_API_PREFIX),
        testcase_api_prefix=getattr(args, "testcase_api_prefix", None)
        or os.getenv("ZENTAO_TESTCASE_API_PREFIX", DEFAULT_TESTCASE_API_PREFIX),
        resolve_bug_after_comment=resolve_bug_after_comment,
        account=args.account or os.getenv("ZENTAO_ACCOUNT"),
        password=args.password or os.getenv("ZENTAO_PASSWORD"),
        resolved_build=_clean_optional_string(
            getattr(args, "resolved_build", None) or os.getenv("ZENTAO_RESOLVED_BUILD")
        )
        or DEFAULT_RESOLVED_BUILD,
    )
    if not client.base_url:
        raise ZenTaoError("Set ZENTAO_BASE_URL or pass --base-url.")

    if not client.token and client.account and client.password:
        client.login(client.account, client.password)
    if not client.token:
        raise ZenTaoError("Set ZENTAO_TOKEN, or provide ZENTAO_ACCOUNT and ZENTAO_PASSWORD.")
    return client


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ZenTao REST helper for Codex skills.")
    parser.add_argument("--base-url")
    parser.add_argument("--api-prefix")
    parser.add_argument(
        "--testcase-api-prefix",
        help=f"ZenTao API prefix for testcase creation; defaults to {DEFAULT_TESTCASE_API_PREFIX}.",
    )
    parser.add_argument("--token")
    parser.add_argument("--account")
    parser.add_argument("--password")
    parser.add_argument(
        "--resolve-bug-after-comment",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Resolve the bug after a successful comment; defaults to ZENTAO_RESOLVE_BUG_AFTER_COMMENT.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("products")

    bugs_parser = subparsers.add_parser("bugs")
    bugs_parser.add_argument("product_id", type=int)
    bugs_parser.add_argument("--all", action="store_true", help="Include resolved and closed bugs.")
    bugs_parser.add_argument("--include-non-code", action="store_true", help="Include non-code bug types.")

    bug_parser = subparsers.add_parser("bug")
    bug_parser.add_argument("bug_id", type=int)

    bug_update_parser = subparsers.add_parser("bug-update")
    bug_update_parser.add_argument("bug_id", type=int)
    bug_update_parser.add_argument("--type", dest="bug_type", required=True, help="ZenTao bug type value.")

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("bug_id", type=int)
    resolve_parser.add_argument(
        "--resolution",
        default="fixed",
        help="ZenTao resolve value; defaults to fixed.",
    )
    resolve_parser.add_argument(
        "--resolved-build",
        help=f"ZenTao resolvedBuild value used for this resolve; defaults to {DEFAULT_RESOLVED_BUILD}.",
    )

    comment_parser = subparsers.add_parser("comment")
    comment_parser.add_argument("bug_id", type=int)
    comment_parser.add_argument("--cause", required=True)
    comment_parser.add_argument("--solution", required=True)
    comment_parser.add_argument(
        "--resolved-build",
        help=f"ZenTao resolvedBuild value used when resolve-after-comment is enabled; defaults to {DEFAULT_RESOLVED_BUILD}.",
    )

    testcase_upload_parser = subparsers.add_parser("testcase-upload")
    testcase_upload_parser.add_argument("json_file", type=Path)
    testcase_upload_parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue uploading remaining test cases after one case fails.",
    )

    args = parser.parse_args(argv)
    try:
        client = _build_client(args)
        if args.command == "products":
            _print_json(client.products())
        elif args.command == "bugs":
            bugs = client.product_bugs(args.product_id)
            if args.all:
                if not args.include_non_code:
                    bugs = [bug for bug in bugs if is_code_bug(bug)]
            elif args.include_non_code:
                bugs = unresolved_bugs(bugs)
            else:
                bugs = repairable_bugs(bugs)
            _print_json(sorted(bugs, key=bug_sort_key))
        elif args.command == "bug":
            _print_json(client.bug(args.bug_id))
        elif args.command == "bug-update":
            _print_json(client.update_bug(args.bug_id, bug_type=args.bug_type))
        elif args.command == "resolve":
            _print_json(
                client.resolve_bug(
                    args.bug_id,
                    resolution=args.resolution,
                    resolved_build=getattr(args, "resolved_build", None),
                )
            )
        elif args.command == "comment":
            _print_json(client.comment_bug(args.bug_id, args.cause, args.solution))
        elif args.command == "testcase-upload":
            result = upload_test_case_batch(
                client,
                load_test_case_batch(args.json_file),
                continue_on_error=args.continue_on_error,
            )
            _print_json(result)
            if result["failed"]:
                return 1
        return 0
    except (ZenTaoError, ValueError) as exc:
        print(f"zentao_client: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
