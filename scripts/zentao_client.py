#!/usr/bin/env python3
"""Small ZenTao REST client for Codex skills.

The module intentionally uses only the Python standard library so the skill can
be copied into any business repository without dependency installation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_API_PREFIX = "/api.php/v1"


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
    timeout: int = 30

    @classmethod
    def from_env(cls) -> "ZenTaoClient":
        base_url = os.getenv("ZENTAO_BASE_URL")
        if not base_url:
            raise ZenTaoError("Missing ZENTAO_BASE_URL.")
        return cls(
            base_url=base_url,
            token=os.getenv("ZENTAO_TOKEN"),
            api_prefix=os.getenv("ZENTAO_API_PREFIX", DEFAULT_API_PREFIX),
        )

    def url(self, path: str, query: Optional[Dict[str, Any]] = None) -> str:
        full = _strip_join(_strip_join(self.base_url, self.api_prefix), path)
        clean_query = {
            key: value
            for key, value in (query or {}).items()
            if value is not None and value != ""
        }
        if clean_query:
            full = f"{full}?{urlencode(clean_query)}"
        return full

    def request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
    ) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Token"] = self.token
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(self.url(path, query), data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return _json_loads(response.read())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ZenTaoError(f"ZenTao HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ZenTaoError(f"ZenTao request failed: {exc.reason}") from exc

    def get(self, path: str, query: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("GET", path, query=query)

    def post(self, path: str, payload: Dict[str, Any]) -> Any:
        return self.request("POST", path, payload=payload)

    def put(self, path: str, payload: Dict[str, Any]) -> Any:
        return self.request("PUT", path, payload=payload)

    def login(self, account: str, password: str) -> str:
        data = self.post("/tokens", {"account": account, "password": password})
        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise ZenTaoError("Login succeeded but response did not contain token.")
        self.token = token
        return token

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

    def comment_bug(self, bug_id: int, cause: str, solution: str) -> Any:
        return self.put(f"/bugs/{bug_id}", build_bug_comment_payload(cause=cause, solution=solution))


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
    comment = f"问题原因：{cause.strip()}\n\n解决方案：{solution.strip()}"
    return {"comment": comment}


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _build_client(args: argparse.Namespace) -> ZenTaoClient:
    client = ZenTaoClient(
        base_url=args.base_url or os.getenv("ZENTAO_BASE_URL", ""),
        token=args.token or os.getenv("ZENTAO_TOKEN"),
        api_prefix=args.api_prefix or os.getenv("ZENTAO_API_PREFIX", DEFAULT_API_PREFIX),
    )
    if not client.base_url:
        raise ZenTaoError("Set ZENTAO_BASE_URL or pass --base-url.")

    account = args.account or os.getenv("ZENTAO_ACCOUNT")
    password = args.password or os.getenv("ZENTAO_PASSWORD")
    if not client.token and account and password:
        client.login(account, password)
    if not client.token:
        raise ZenTaoError("Set ZENTAO_TOKEN, or provide ZENTAO_ACCOUNT and ZENTAO_PASSWORD.")
    return client


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ZenTao REST helper for Codex skills.")
    parser.add_argument("--base-url")
    parser.add_argument("--api-prefix")
    parser.add_argument("--token")
    parser.add_argument("--account")
    parser.add_argument("--password")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("products")

    bugs_parser = subparsers.add_parser("bugs")
    bugs_parser.add_argument("product_id", type=int)
    bugs_parser.add_argument("--all", action="store_true", help="Include resolved and closed bugs.")

    bug_parser = subparsers.add_parser("bug")
    bug_parser.add_argument("bug_id", type=int)

    comment_parser = subparsers.add_parser("comment")
    comment_parser.add_argument("bug_id", type=int)
    comment_parser.add_argument("--cause", required=True)
    comment_parser.add_argument("--solution", required=True)

    args = parser.parse_args(argv)
    try:
        client = _build_client(args)
        if args.command == "products":
            _print_json(client.products())
        elif args.command == "bugs":
            bugs = client.product_bugs(args.product_id)
            if not args.all:
                bugs = unresolved_bugs(bugs)
            _print_json(sorted(bugs, key=bug_sort_key))
        elif args.command == "bug":
            _print_json(client.bug(args.bug_id))
        elif args.command == "comment":
            _print_json(client.comment_bug(args.bug_id, args.cause, args.solution))
        return 0
    except ZenTaoError as exc:
        print(f"zentao_client: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
