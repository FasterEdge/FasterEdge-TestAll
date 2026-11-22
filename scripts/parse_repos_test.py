#!/usr/bin/env python3
"""scripts/parse_repos.py 的最小测试。

覆盖:
  1. skip 条目被剔除, 且不进入 matrix.include;
  2. skip 却没写 reason -> 判为无效清单(这是"显式标 skip 并说明原因"的硬约束);
  3. 未 skip 却写 reason -> 判为无效清单(防止清单自相矛盾);
  4. commands 为空 -> 判为无效清单(防止写占位命令);
  5. needs_go / needs_node 由 commands 推断;
  6. 仓库名过滤 (workflow_dispatch 的 selected 参数) 生效;
  7. 默认 go_version 由 defaults 提供, 条目可覆盖;
  8. --github-output 写出的单行 JSON 可被 fromJSON 解析。

运行: python3 scripts/parse_repos_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_repos import ManifestError, build_include, load_manifest  # noqa: E402
from parse_repos import main as parse_main  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        FAILURES.append(label)


def write_manifest(directory: str, text: str) -> str:
    path = os.path.join(directory, "repos.yml")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


BASE = """
version: 1
defaults:
  go_version: '1.27.4'
repos:
  - name: Alpha
    url: https://example.invalid/Alpha.git
    ref: main
    commands: ['go vet ./...', 'go test -count=1 ./...']
  - name: Beta
    url: https://example.invalid/Beta.git
    commands: ['npm ci', 'npm run build']
"""


def test_skip_requires_reason() -> None:
    print("skip 必须带 reason")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_manifest(tmp, BASE + """
  - name: Gamma
    url: https://example.invalid/Gamma.git
    skip: true
    commands: ['make']
""")
        manifest = load_manifest(path)
        try:
            build_include(manifest, [])
            check(False, "skip 无 reason 应抛 ManifestError")
        except ManifestError as exc:
            check("Gamma" in str(exc), f"错误信息点名了仓库: {exc}")


def test_reason_without_skip_is_invalid() -> None:
    print("未 skip 却写 reason 属无效清单")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_manifest(tmp, BASE + """
  - name: Delta
    url: https://example.invalid/Delta.git
    reason: '写错了'
    commands: ['go build ./...']
""")
        manifest = load_manifest(path)
        try:
            build_include(manifest, [])
            check(False, "reason 与 skip 不一致应抛 ManifestError")
        except ManifestError:
            check(True, "reason 与 skip 不一致被拒绝")


def test_empty_commands_is_invalid() -> None:
    print("commands 不能为空")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_manifest(tmp, """
version: 1
repos:
  - name: Empty
    url: https://example.invalid/Empty.git
    commands: []
""")
        manifest = load_manifest(path)
        try:
            build_include(manifest, [])
            check(False, "空 commands 应抛 ManifestError")
        except ManifestError as exc:
            check("commands" in str(exc), f"错误信息指向 commands: {exc}")


def test_matrix_shape() -> None:
    print("matrix.include 结构与 skip 剔除")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_manifest(tmp, BASE + """
  - name: Eps
    url: https://example.invalid/Eps.git
    skip: true
    reason: '本机构建条件不具备'
    commands: ['make iso']
""")
        manifest = load_manifest(path)
        include = build_include(manifest, [])
        names = [item["name"] for item in include]
        check(names == ["Alpha", "Beta"], f"skip 条目已剔除, 保留 {names}")

        alpha = include[0]
        check(alpha["ref"] == "main", "ref 透传")
        check(alpha["go_version"] == "1.27.4", "默认 go_version 生效")
        check(alpha["needs_go"] is True, "Alpha needs_go=True")
        check(alpha["needs_node"] is False, "Alpha needs_node=False")
        check(alpha["commands"] == ["go vet ./...", "go test -count=1 ./..."],
              "commands 原样透传")

        beta = include[1]
        check(beta["needs_node"] is True, "Beta needs_node=True")
        check(beta["needs_go"] is False, "Beta needs_go=False")
        check(beta["go_version"] == "1.27.4", "Beta 沿用默认 go_version")

        # 产出必须能被 GitHub Actions 的 fromJSON 解析
        round_trip = json.loads(json.dumps(include))
        check(round_trip == include, "JSON 序列化可往返")


def test_selection_filter() -> None:
    print("仓库名过滤")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_manifest(tmp, BASE)
        manifest = load_manifest(path)
        check([i["name"] for i in build_include(manifest, ["Beta"])] == ["Beta"],
              "只保留 Beta")
        try:
            build_include(manifest, ["Nope"])
            check(False, "未知仓库名应抛 ManifestError")
        except ManifestError as exc:
            check("Nope" in str(exc), f"未知仓库名被点名: {exc}")


def test_github_output_is_single_line() -> None:
    print("--github-output 单行输出")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_manifest(tmp, BASE)
        out = os.path.join(tmp, "gh_output")
        rc = parse_main([path, "--github-output", out])
        check(rc == 0, "退出码 0")
        with open(out, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        check(len(lines) == 1, f"只写一行 (实际 {len(lines)} 行)")
        check(lines[0].startswith("include="), "输出为 include=... 形式")
        payload = lines[0][len("include="):]
        parsed = json.loads(payload)
        check([i["name"] for i in parsed] == ["Alpha", "Beta"], "内容可解析为 JSON 数组")
        check("\n" not in payload, "payload 不含换行")


def test_repo_level_go_version_override() -> None:
    print("条目级 go_version 覆盖")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_manifest(tmp, BASE.replace("ref: main", "ref: main\n    go_version: '1.25.0'"))
        manifest = load_manifest(path)
        include = build_include(manifest, [])
        check(include[0]["go_version"] == "1.25.0", "条目覆盖 defaults")
        check(include[1]["go_version"] == "1.27.4", "其余条目仍用 defaults")


def main() -> int:
    test_skip_requires_reason()
    test_reason_without_skip_is_invalid()
    test_empty_commands_is_invalid()
    test_matrix_shape()
    test_selection_filter()
    test_github_output_is_single_line()
    test_repo_level_go_version_override()

    print()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项:")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("全部测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
