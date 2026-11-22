#!/usr/bin/env python3
"""在本地对 repos.yml 的条目实际执行检查命令（不 clone，直接用本地同名目录）。

CI 走 .github/workflows/regression.yml：clone → 执行 commands。
本机验证走这个脚本：各组件仓库已经在本地磁盘上，跳过 clone 直接执行 commands，
这样可以在不联网、不污染远端的前提下确认"清单里每条命令真的能跑通"。

用法:
    python3 scripts/run_local.py --root D:/Projects/FasterEdge [仓库名 ...]
    python3 scripts/run_local.py --root . --list

退出码: 0 表示所有非 skip 条目全部通过; 1 表示有失败; 2 表示清单/环境问题。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_repos import ManifestError, build_include, load_manifest  # noqa: E402

GO_BIN_HINT = (
    "Go 工具链不在默认 PATH 时, 先执行: "
    'export PATH="/c/Users/Dlut/AppData/Roaming/CherryStudio/Toolchain/mise/'
    'installs/go/1.27.0/bin:$PATH"'
)


def resolve_go_bin() -> str | None:
    """找到一个可用的 go 可执行文件所在目录。

    本机默认 PATH 里的 go 是坏掉的 mise shim(会报 'failed to execute mise'),
    因此这里按组织约定的安装路径探测一次, 命中就前置到 PATH。
    找不到时返回 None, 由调用方给出提示, 不静默放过。
    """
    if os.environ.get("GO_BIN"):
        return os.environ["GO_BIN"]

    candidates = [
        os.path.expanduser(
            "~/AppData/Roaming/CherryStudio/Toolchain/mise/installs/go/1.27.0/bin"
        ),
        shutil.which("go"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isfile(os.path.join(candidate, "go.exe")) or os.path.isfile(
            os.path.join(candidate, "go")
        ):
            return candidate
    return None


def run_entry(entry: dict, root: str) -> tuple[bool, list[str]]:
    """在 root/name 下顺序执行 entry 的 commands, 返回 (是否全通过, 日志行)。"""
    workdir = os.path.join(root, entry["name"])
    log: list[str] = []

    if not os.path.isdir(workdir):
        return False, [f"目录不存在: {workdir}"]

    env = os.environ.copy()
    go_bin = resolve_go_bin()
    if go_bin:
        env["PATH"] = go_bin + os.pathsep + env.get("PATH", "")

    for cmd in entry["commands"]:
        started = time.time()
        print(f"  $ {cmd}", flush=True)
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            shell=True,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = time.time() - started
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-6:]
        for line in tail:
            print(f"    {line}", flush=True)
        status = "OK " if proc.returncode == 0 else "FAIL"
        log.append(f"{status} [{elapsed:6.1f}s] {cmd}")
        if proc.returncode != 0:
            return False, log

    return True, log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按 repos.yml 在本地执行各仓检查命令")
    parser.add_argument("--root", default=".", help="各组件仓库的父目录")
    parser.add_argument("--manifest", default=None, help="repos.yml 路径, 默认在脚本上一级")
    parser.add_argument("--list", action="store_true", help="只列出清单条目, 不执行")
    parser.add_argument("selected", nargs="*", help="只跑这些仓库名")
    args = parser.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    manifest_path = args.manifest or os.path.join(os.path.dirname(here), "repos.yml")

    try:
        manifest = load_manifest(manifest_path)
        entries = build_include(manifest, args.selected)
    except (ManifestError, OSError) as exc:
        print(f"repos.yml 无效: {exc}", file=sys.stderr)
        return 2

    if args.list:
        for entry in entries:
            print(f"{entry['name']:42s} {'; '.join(entry['commands'])}")
        return 0

    print(GO_BIN_HINT)
    go_bin = resolve_go_bin()
    if go_bin:
        print(f"Go 工具链: {go_bin}")
    else:
        print("警告: 未找到可用 Go 工具链, 含 go 命令的条目会失败")
    print(f"清单: {manifest_path}")
    print(f"根目录: {os.path.abspath(args.root)}")
    print(f"待执行条目: {len(entries)}\n")

    results: dict[str, bool] = {}
    for entry in entries:
        print(f"== {entry['name']} ==", flush=True)
        ok, log = run_entry(entry, args.root)
        results[entry["name"]] = ok
        for line in log:
            print(f"  {line}", flush=True)
        print(flush=True)

    failed = [name for name, ok in results.items() if not ok]
    print("=" * 60)
    print(f"通过 {len(results) - len(failed)}/{len(results)}")
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if failed:
        print(f"\n失败: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
