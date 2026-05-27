#!/usr/bin/env python3
"""Interactive ZenTao bug selection flow for Codex."""

from __future__ import annotations

import argparse
import html
import re
import sys
from typing import Any, Dict, List, Optional

from zentao_client import ZenTaoClient, ZenTaoError, bug_sort_key, repairable_bugs


def clean_text(value: Any, limit: Optional[int] = None) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip() + "..."
    return text


def format_product_summary(products: List[Dict[str, Any]]) -> str:
    lines = ["ZenTao 产品列表："]
    for index, product in enumerate(products, start=1):
        product_id = product.get("id")
        name = product.get("name") or product.get("title") or "(未命名产品)"
        lines.append(f"{index}. [{product_id}] {name}")
    return "\n".join(lines)


def format_bug_summary(bugs: List[Dict[str, Any]]) -> str:
    lines = ["未解决 Bug："]
    for index, bug in enumerate(bugs, start=1):
        bug_id = bug.get("id")
        pri = bug.get("pri", "-")
        severity = bug.get("severity", "-")
        title = clean_text(bug.get("title"), 120)
        steps = clean_text(bug.get("steps"), 120)
        lines.append(f"{index}. #{bug_id} P{pri} S{severity} {title}")
        if steps:
            lines.append(f"   steps: {steps}")
    return "\n".join(lines)


def assignee_identity(bug: Dict[str, Any]) -> Dict[str, str]:
    assigned_to = bug.get("assignedTo")
    if isinstance(assigned_to, dict):
        account = str(assigned_to.get("account") or assigned_to.get("id") or "").strip()
        realname = str(assigned_to.get("realname") or assigned_to.get("name") or "").strip()
    else:
        account = str(assigned_to or "").strip()
        realname = ""
    key = account or realname or "(unassigned)"
    label = f"{account} / {realname}" if account and realname else key
    return {"key": key, "account": account, "realname": realname, "label": label}


def assignee_groups(bugs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for bug in bugs:
        identity = assignee_identity(bug)
        key = identity["key"]
        if key not in grouped:
            grouped[key] = {"key": key, "label": identity["label"], "accounts": {identity["account"], identity["realname"]}, "bugs": []}
        grouped[key]["bugs"].append(bug)
    return sorted(grouped.values(), key=lambda item: (-len(item["bugs"]), item["label"].lower()))


def format_assignee_summary(bugs: List[Dict[str, Any]]) -> str:
    lines = ["请选择要批量修复的指派人："]
    for index, group in enumerate(assignee_groups(bugs), start=1):
        count = len(group["bugs"])
        suffix = "bug" if count == 1 else "bugs"
        lines.append(f"{index}. {group['label']} ({count} {suffix})")
    return "\n".join(lines)


def parse_assignee_selection(raw: str, bugs: List[Dict[str, Any]]) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("Empty assignee selection.")

    groups = assignee_groups(bugs)
    if value.isdigit():
        number = int(value)
        if 1 <= number <= len(groups):
            return str(groups[number - 1]["key"])

    folded = value.casefold()
    for group in groups:
        candidates = {str(group["key"]).casefold(), str(group["label"]).casefold()}
        candidates.update(str(item).casefold() for item in group["accounts"] if item)
        if folded in candidates:
            return str(group["key"])
    raise ValueError(f"No assignee matched selection: {raw}")


def bugs_for_assignee(assignee: str, bugs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected = []
    folded = assignee.casefold()
    for bug in bugs:
        identity = assignee_identity(bug)
        candidates = {identity["key"].casefold(), identity["account"].casefold(), identity["realname"].casefold()}
        if folded in candidates:
            selected.append(bug)
    return selected


def load_repairable_bugs(client: ZenTaoClient, product_id: int) -> List[Dict[str, Any]]:
    return repairable_bugs(client.product_bugs(product_id))


def bug_context(bug: Dict[str, Any]) -> str:
    fields = [
        ("Bug ID", bug.get("id")),
        ("标题", clean_text(bug.get("title"))),
        ("优先级", bug.get("pri")),
        ("严重程度", bug.get("severity")),
        ("类型", bug.get("type")),
        ("操作系统", bug.get("os")),
        ("浏览器", bug.get("browser")),
        ("关键词", clean_text(bug.get("keywords"))),
        ("复现步骤", clean_text(bug.get("steps"))),
    ]
    lines = ["## ZenTao Bug Context"]
    for label, value in fields:
        if value not in (None, ""):
            lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def prompt(message: str) -> str:
    return input(f"{message}\n> ")


def run_interactive(args: argparse.Namespace) -> int:
    client = ZenTaoClient.from_env()
    if not client.token:
        account = args.account
        password = args.password
        if not account or not password:
            raise ZenTaoError("Set ZENTAO_TOKEN or provide --account and --password.")
        client.login(account, password)

    products = client.products()
    print(format_product_summary(products))
    raw_product = args.product or prompt("请选择产品序号或产品 ID")
    product_id = _resolve_product_id(raw_product, products)

    bugs = sorted(load_repairable_bugs(client, product_id), key=bug_sort_key)
    if not bugs:
        print("该产品没有未解决且类型为代码问题的 Bug。")
        return 0

    print(format_assignee_summary(bugs))
    raw_assignee = args.assigned_to or prompt("请选择指派人序号、账号或姓名，将批量修复该用户所有未解决且类型为代码问题的 Bug")
    assignee = parse_assignee_selection(raw_assignee, bugs)
    selected = sorted(bugs_for_assignee(assignee, bugs), key=bug_sort_key)
    print(format_bug_summary(selected))

    for bug in selected:
        detail = client.bug(int(bug["id"]))
        print()
        print(bug_context(detail))
        print()
        print("把上面的上下文交给 Codex 在当前业务项目中定位、修改、验证。")
        print("修复并验证通过后，使用 zentao_client.py comment 仅写入问题原因和解决方案备注，不修改 Bug 状态。")
    return 0


def _resolve_product_id(raw: str, products: List[Dict[str, Any]]) -> int:
    value = raw.strip()
    number = int(value)
    if 1 <= number <= len(products):
        return int(products[number - 1]["id"])
    for product in products:
        if int(product.get("id", -1)) == number:
            return number
    raise ValueError(f"No product matched selection: {raw}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Select ZenTao unresolved bugs for Codex repair work.")
    parser.add_argument("--account", help="ZenTao account; prefer ZENTAO_ACCOUNT in normal use.")
    parser.add_argument("--password", help="ZenTao password; prefer ZENTAO_PASSWORD in normal use.")
    parser.add_argument("--product", help="Product index or product ID.")
    parser.add_argument("--assigned-to", help="Assignee index, account, or real name.")
    args = parser.parse_args(argv)
    try:
        return run_interactive(args)
    except (ZenTaoError, ValueError) as exc:
        print(f"zentao_bug_flow: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
