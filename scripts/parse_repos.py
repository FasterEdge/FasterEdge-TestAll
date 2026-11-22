#!/usr/bin/env python3
"""把 repos.yml 解析成 GitHub Actions 的 matrix.include JSON。

用法:
    python3 scripts/parse_repos.py repos.yml [--github-output FILE] [仓库名 ...]

为什么用脚本而不是在 YAML 里直接写 matrix:
    GitHub Actions 的 matrix 表达式无法读文件内容, 而 repos.yml 需要按条目
    携带 commands(字符串数组)、go_version、needs_go/needs_node 等字段,
    并且要支持 workflow_dispatch 的仓库名过滤。这些逻辑放在脚本里可读、可测。

    GitHub Actions 会把本脚本打印到 stdout 的最后一行当作 job output,
    因此调试信息一律写 stderr, stdout 只保留最终 JSON。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - 由 workflow 的 python3 环境保证
    yaml = None


class ManifestError(Exception):
    """repos.yml 内容不符合约定。"""


def _fail(message: str) -> "ManifestError":
    return ManifestError(message)


def load_manifest(path: str) -> dict:
    """读取并校验 repos.yml 的基本结构。"""
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise _fail(f"{path}: 顶层必须是 mapping")

    repos = data.get("repos")
    if not isinstance(repos, list) or not repos:
        raise _fail(f"{path}: 缺少非空的 repos 列表")

    return data


def _validate_repo(entry: dict, index: int) -> None:
    """校验单条目的字段, 提前把常见的清单笔误挡在 CI 之外。"""
    where = f"repos[{index}]"
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        raise _fail(f"{where}.name 缺失或不是字符串")
    where = f"repos[{index}]({name})"

    if not isinstance(entry.get("url"), str) or not entry["url"]:
        raise _fail(f"{where}.url 缺失")

    skip = bool(entry.get("skip", False))
    reason = entry.get("reason", "")
    if skip and not isinstance(reason, str):
        raise _fail(f"{where}.reason 必须是字符串")
    if skip and not reason.strip():
        raise _fail(f"{where} 标了 skip 但没写 reason; 必须说明为什么不能跑")
    if not skip and reason.strip():
        raise _fail(f"{where} 未 skip 却写了 reason; 二者必须一致")

    commands = entry.get("commands")
    if skip:
        # skip 条目只作记录, 允许暂不写 commands; 一旦写了仍要逐条合法
        if commands is not None and not isinstance(commands, list):
            raise _fail(f"{where}.commands 必须是列表")
        commands = commands or []
    elif not isinstance(commands, list) or not commands:
        raise _fail(f"{where}.commands 缺失或为空列表")
    for cmd in commands:
        if not isinstance(cmd, str) or not cmd.strip():
            raise _fail(f"{where}.commands 含空命令")

    go_version = entry.get("go_version")
    if go_version is not None and not isinstance(go_version, str):
        raise _fail(f"{where}.go_version 必须是字符串")


def build_include(manifest: dict, selected: list[str]) -> list[dict]:
    """把 repos.yml 转成 matrix.include 条目, 跳过 skip: true 的条目。"""
    defaults = manifest.get("defaults") or {}
    default_go = defaults.get("go_version")

    if selected:
        known = {repo.get("name") for repo in manifest["repos"]}
        unknown = [name for name in selected if name not in known]
        if unknown:
            raise _fail(f"未知仓库名: {', '.join(sorted(unknown))}")

    include: list[dict] = []
    for index, entry in enumerate(manifest["repos"]):
        _validate_repo(entry, index)

        name = entry["name"]
        if selected and name not in selected:
            continue

        if entry.get("skip", False):
            print(f"[parse] {name}: skip -> {entry['reason']}", file=sys.stderr)
            continue

        commands = entry["commands"]
        needs_go = any(cmd.startswith("go ") or " go build" in cmd for cmd in commands)
        needs_node = any(cmd.startswith("npm ") or "npm ci" in cmd for cmd in commands)

        include.append(
            {
                "name": name,
                "ref": entry.get("ref") or "",
                "go_version": str(entry.get("go_version") or default_go or ""),
                "commands": commands,
                "needs_go": needs_go,
                "needs_node": needs_node,
            }
        )

    return include


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 repos.yml 转成 GitHub matrix JSON")
    parser.add_argument("manifest", help="repos.yml 路径")
    parser.add_argument("--github-output", help="写入 key=value 形式的 $GITHUB_OUTPUT 文件")
    parser.add_argument("selected", nargs="*", help="只保留这些仓库名, 逗号分隔可混用")
    args = parser.parse_args(argv)

    if yaml is None:
        print("[parse] 需要 PyYAML; 请先在 runner 上安装", file=sys.stderr)
        return 2

    selected: list[str] = []
    for chunk in args.selected:
        selected.extend(part.strip() for part in chunk.split(",") if part.strip())

    try:
        manifest = load_manifest(args.manifest)
        include = build_include(manifest, selected)
    except (ManifestError, OSError, yaml.YAMLError) as exc:
        print(f"[parse] repos.yml 无效: {exc}", file=sys.stderr)
        return 1

    payload = json.dumps(include, ensure_ascii=False)
    # GitHub Actions 的 job output 只能是一行, 且表达式里不能出现换行
    payload = payload.replace("\n", "")

    print(f"[parse] matrix 条目 {len(include)} 个", file=sys.stderr)
    if not include:
        print("[parse] 没有可执行的仓库, 回归 job 将被跳过", file=sys.stderr)

    if args.github_output:
        # 必须显式写 '\n': 文本模式下 os.linesep 会被再翻译一次,
        # 在 Windows 上产生 '\r\r\n', 把单行 output 拆成两行。
        with open(args.github_output, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"include={payload}\n")
    else:
        print(payload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
