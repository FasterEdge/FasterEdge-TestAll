#!/usr/bin/env python3
"""repos.yml 与 workflow YAML 的最小校验脚本（本机无 actionlint 时的替代）。

检查内容:
  1. repos.yml 与 .github/workflows/*.yml 都能被 YAML 解析;
  2. workflow 的顶层必备键存在 (name / on / jobs), jobs 下每个 job 有 runs-on;
  3. workflow 引用的本地脚本路径真实存在;
  4. repos.yml 的条目符合 scripts/parse_repos.py 的约定 (含 skip 必须写 reason)。

用法:
    python3 scripts/check_manifest.py [仓库根目录, 默认脚本上一级]

退出码: 0 全部通过; 1 有校验失败; 2 缺少 PyYAML。
"""

from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_repos import ManifestError, load_manifest, _validate_repo  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def check_workflow(path: str) -> list[str]:
    """校验单个 workflow 文件的基本结构。"""
    errors: list[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        try:
            doc = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            return [f"{path}: YAML 解析失败: {exc}"]

    if not isinstance(doc, dict):
        return [f"{path}: 顶层必须是 mapping"]

    for key in ("name", "jobs"):
        if key not in doc:
            errors.append(f"{path}: 缺少顶层键 {key}")
    # PyYAML 把裸 on 解析成布尔 True, 这里两种写法都接受
    if "on" not in doc and True not in doc:
        errors.append(f"{path}: 缺少触发条件 on")

    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        errors.append(f"{path}: jobs 必须是非空 mapping")
        return errors

    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            errors.append(f"{path}: jobs.{job_name} 必须是 mapping")
            continue
        if "uses" not in job and "runs-on" not in job:
            errors.append(f"{path}: jobs.{job_name} 既无 runs-on 也无 uses")

    return errors


def check_script_refs(path: str, root: str) -> list[str]:
    """确认 workflow 里引用的本地脚本路径真实存在。

    只认 `python3 scripts/xxx.py` 这种"以已知脚本名结尾"的 token,
    避免把 `paths: [scripts/**]` 里的通配符当成文件路径。
    """
    errors: list[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()

    for token in text.replace('"', " ").replace("'", " ").split():
        if not token.startswith("scripts/"):
            continue
        if any(ch in token for ch in "*?[]"):
            continue
        if not token.endswith(".py") and not token.endswith(".sh"):
            continue
        candidate = os.path.join(root, token)
        if not os.path.exists(candidate):
            errors.append(f"{path}: 引用的脚本不存在: {token}")
    return errors


def main(argv: list[str]) -> int:
    root = argv[1] if len(argv) > 1 else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )

    if yaml is None:
        print("需要 PyYAML: python -m pip install pyyaml", file=sys.stderr)
        return 2

    errors: list[str] = []

    manifest_path = os.path.join(root, "repos.yml")
    try:
        manifest = load_manifest(manifest_path)
        for index, entry in enumerate(manifest["repos"]):
            _validate_repo(entry, index)
        names = [entry["name"] for entry in manifest["repos"]]
        if len(names) != len(set(names)):
            errors.append("repos.yml: 存在重名条目")
        print(f"repos.yml: {len(names)} 个条目, "
              f"skip {sum(1 for e in manifest['repos'] if e.get('skip'))} 个")
    except (ManifestError, OSError) as exc:
        errors.append(f"repos.yml: {exc}")

    for path in sorted(glob.glob(os.path.join(root, ".github", "workflows", "*.yml"))):
        before = len(errors)
        errors.extend(check_workflow(path))
        errors.extend(check_script_refs(path, root))
        if len(errors) == before:
            print(f"{os.path.relpath(path, root)}: OK")
        else:
            print(f"{os.path.relpath(path, root)}: FAILED")

    if errors:
        print("\n校验失败:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("\n全部校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
