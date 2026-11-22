#!/usr/bin/env python3
"""在本地对 repos.yml 的条目实际执行检查命令（不 clone，直接用本地同名目录）。

CI 走 .github/workflows/regression.yml：clone → 执行 commands。
本机验证走这个脚本：各组件仓库已经在本地磁盘上，跳过 clone 直接执行 commands，
这样可以在不联网、不污染远端的前提下确认"清单里每条命令真的能跑通"。

Go 工具链解析顺序（不硬编码版本号）:
  1. 环境变量 GO_BIN 指向的目录;
  2. 本机组织约定的 mise 安装根目录下, 按 `repos.yml` 的 defaults.go_version
     拼出的 `.../go/<version>/bin`;
  3. 同一安装根下已存在的 go/<version>/bin 中版本最高的一个（版本号来自目录名，
     不来自本脚本写死的常量）;
  4. PATH 里的 go（可能是坏掉的 mise shim, 兜底）。

`--no-fix-npm-proxy`（默认关闭规避时才加）: 本机 `~/.npmrc` 把代理固定到已失效的
127.0.0.1:7897, 直接 `npm ci` 会 ECONNREFUSED。默认情况下脚本为每条 npm 类命令生成
一份只含 `registry=https://registry.npmjs.org/` 的临时 userconfig 并用
`npm_config_userconfig` 注入, 不动用户自己的 `~/.npmrc`; 加该开关可复现原始失败。
CI runner 无此问题。

用法:
    python3 scripts/run_local.py --root D:/Projects/FasterEdge [仓库名 ...]
    python3 scripts/run_local.py --root . --list
    python3 scripts/run_local.py --root . --no-fix-npm-proxy

退出码: 0 表示所有非 skip 条目全部通过; 1 表示有失败; 2 表示清单/环境问题。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_repos import ManifestError, build_include, load_manifest  # noqa: E402

# 组织约定的 mise 安装根, 只用来兜底探测, 具体版本号一律来自 repos.yml / 目录名
MISE_GO_ROOT = os.path.expanduser(
    "~/AppData/Roaming/CherryStudio/Toolchain/mise/installs/go"
)

VERSION_DIR_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")

# 临时 userconfig 的内容: 只指定 registry, 不继承任何代理设置。
# 显式留空代理键会触发 npm 的 "Must be full url with http://" 警告,
# 因此干脆不写代理键——不写即默认无代理。
CLEAN_NPMRC = "registry=https://registry.npmjs.org/\n"


def _version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in version.split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts)


def _go_bin_candidates(requested: str | None) -> list[str]:
    """按优先级给出候选 Go bin 目录; requested 是 repos.yml 声明的版本。"""
    candidates: list[str] = []
    if requested:
        candidates.append(os.path.join(MISE_GO_ROOT, requested, "bin"))
    # 安装根下实际存在的版本目录, 取版本号最大的那个
    found: list[str] = []
    try:
        for entry in os.listdir(MISE_GO_ROOT):
            if VERSION_DIR_RE.match(entry):
                bin_dir = os.path.join(MISE_GO_ROOT, entry, "bin")
                if os.path.isfile(os.path.join(bin_dir, "go.exe")) or os.path.isfile(
                    os.path.join(bin_dir, "go")
                ):
                    found.append(entry)
    except OSError:
        pass
    for entry in sorted(found, key=_version_key, reverse=True):
        candidates.append(os.path.join(MISE_GO_ROOT, entry, "bin"))
    return candidates


def resolve_go_bin(requested: str | None = None) -> str | None:
    """找到一个可用的 go 可执行文件所在目录。

    本机默认 PATH 里的 go 是坏掉的 mise shim(会报 'failed to execute mise'),
    因此这里按组织约定的安装路径探测一次, 命中就前置到 PATH。
    优先级: GO_BIN 环境变量 > repos.yml 声明的版本 > 安装根下最高版本 > PATH。
    找不到时返回 None, 由调用方给出提示, 不静默放过。
    """
    if os.environ.get("GO_BIN"):
        return os.environ["GO_BIN"]

    candidates = _go_bin_candidates(requested)
    which = shutil.which("go")
    if which:
        candidates.append(os.path.dirname(which))

    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isfile(os.path.join(candidate, "go.exe")) or os.path.isfile(
            os.path.join(candidate, "go")
        ):
            return candidate
    return None


def _needs_clean_npmrc(cmd: str) -> bool:
    """这条命令是否是 npm 类命令（需要绕开失效代理的 userconfig）。"""
    return cmd.strip().startswith("npm ")


def run_entry(
    entry: dict,
    root: str,
    fix_npm_proxy: bool = True,
    npmrc_path: str | None = None,
) -> tuple[bool, list[str]]:
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
        # 本机 ~/.npmrc 固定了失效代理, 用干净 userconfig 顶掉它
        if fix_npm_proxy and _needs_clean_npmrc(cmd) and npmrc_path:
            env["npm_config_userconfig"] = npmrc_path
            print(f"    (npm_config_userconfig={npmrc_path}, 绕开本机失效代理)", flush=True)
        else:
            env.pop("npm_config_userconfig", None)
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
    # Windows 控制台默认 GBK, 而被检命令的输出常含 ✓ / 箭头等非 GBK 字符,
    # 直接 print 会抛 UnicodeEncodeError 打断整轮回归(实测 DontCrack-Desktop
    # 的 vite build 输出就撞上过)。这里统一切到 UTF-8 并容许替换字符。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    parser = argparse.ArgumentParser(description="按 repos.yml 在本地执行各仓检查命令")
    parser.add_argument("--root", default=".", help="各组件仓库的父目录")
    parser.add_argument("--manifest", default=None, help="repos.yml 路径, 默认在脚本上一级")
    parser.add_argument("--list", action="store_true", help="只列出清单条目, 不执行")
    parser.add_argument(
        "--no-fix-npm-proxy",
        action="store_true",
        help="不为 npm 命令注入干净的 npm_config_userconfig（复现本机代理失败时用）",
    )
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

    # Go 版本不写死: 先看 repos.yml 的 defaults.go_version, 再回落到探测结果
    requested = (manifest.get("defaults") or {}).get("go_version")
    go_bin = resolve_go_bin(requested)
    if go_bin:
        print(f"Go 工具链: {go_bin} (repos.yml 声明 {requested})")
    else:
        print(
            "警告: 未找到可用 Go 工具链, 含 go 命令的条目会失败。\n"
            f"  已尝试: $GO_BIN, {MISE_GO_ROOT}/<version>/bin "
            f"(repos.yml 声明 {requested}), PATH 中的 go"
        )
    print(f"清单: {manifest_path}")
    print(f"根目录: {os.path.abspath(args.root)}")
    print(f"待执行条目: {len(entries)}")

    fix_npm_proxy = not args.no_fix_npm_proxy
    npmrc_path: str | None = None
    if fix_npm_proxy:
        # 写到临时文件而不是动 ~/.npmrc, 避免污染用户配置
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".npmrc", delete=False, encoding="utf-8", newline="\n"
        )
        with handle:
            handle.write(CLEAN_NPMRC)
        npmrc_path = handle.name
        print(f"npm 规避: 为 npm 命令注入干净 userconfig {npmrc_path}")

    results: dict[str, bool] = {}
    try:
        for entry in entries:
            print(f"== {entry['name']} ==", flush=True)
            ok, log = run_entry(entry, args.root, fix_npm_proxy, npmrc_path)
            results[entry["name"]] = ok
            for line in log:
                print(f"  {line}", flush=True)
            print(flush=True)
    finally:
        if npmrc_path:
            try:
                os.unlink(npmrc_path)
            except OSError:
                pass

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
