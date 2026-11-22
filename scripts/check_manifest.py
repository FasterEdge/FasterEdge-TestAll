#!/usr/bin/env python3
"""repos.yml 与 workflow YAML 的最小校验脚本（本机无 actionlint 时的替代）。

检查内容:
  1. repos.yml 与 .github/workflows/*.yml 都能被 YAML 解析;
  2. workflow 的顶层必备键存在 (name / on / jobs), jobs 下每个 job 有 runs-on;
  3. workflow 引用的本地脚本路径真实存在;
  4. jobs.<job>.needs 引用的前置 job 真实存在, 且 `needs.<job>.outputs.<name>`
     引用的前置 job 既在 needs 列表里、也真的声明了该 output;
  5. repos.yml 的条目符合 scripts/parse_repos.py 的约定 (含 skip 必须写 reason)。

用法:
    python3 scripts/check_manifest.py [仓库根目录, 默认脚本上一级]

退出码: 0 全部通过; 1 有校验失败; 2 缺少 PyYAML。
"""

from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_repos import ManifestError, load_manifest, _validate_repo  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# `needs.<job>` 与 `needs.<job>.outputs.<name>` 的引用。
# 只在 ${{ }} 上下文里生效, 且不能是 needsFoo / xneeds 这类连写标识符。
NEEDS_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_.])needs(?:\.([A-Za-z_][A-Za-z0-9_-]*))"
    r"(?:\.outputs\.([A-Za-z_][A-Za-z0-9_-]*))?"
)


def _iter_expression_texts(job: dict) -> list[str]:
    """递归收集 job 定义里所有可能是表达式的字符串值。

    表达式不止出现在 `if` 里: matrix.include、env、steps.with 都能写
    `needs.xxx.outputs.yyy`。regression.yml 那次就是把引用写在了
    matrix.include 里, 所以必须全量遍历而不是只查 if。
    """
    texts: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    for value in job.values():
        walk(value)
    return texts


def check_needs_refs(path: str, jobs: dict) -> list[str]:
    """校验 needs 引用链, 把"能跑但等于没跑"的表达式笔误挡在 CI 之外。

    典型故障形态: matrix 引用 `needs.matrix.outputs.include`, 但该 job 的
    needs 只有 plan —— YAML 合法、needs 本身没错, 可 matrix 永远展开为空,
    整个回归门禁在 Checks 页静默消失。这类错误只能靠静态比对发现。
    """
    errors: list[str] = []

    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue

        # 1) needs 列出的前置 job 必须存在, 且不能自引用
        needs = job.get("needs")
        declared: list[str] = []
        if needs is None:
            declared = []
        elif isinstance(needs, str):
            declared = [needs]
        elif isinstance(needs, list):
            declared = [item for item in needs if isinstance(item, str)]
            if len(declared) != len(needs):
                errors.append(f"{path}: jobs.{job_name}.needs 列表含非字符串元素")
        else:
            errors.append(f"{path}: jobs.{job_name}.needs 必须是字符串或列表")

        for dep in declared:
            if dep == job_name:
                errors.append(f"{path}: jobs.{job_name}.needs 不能引用自身")
            elif dep not in jobs:
                errors.append(
                    f"{path}: jobs.{job_name}.needs 引用了不存在的前置 job: {dep}"
                )

        # 2) `needs.<job>.outputs.<name>` 的 <job> 必须在 needs 里,
        #    且该前置 job 确实声明了 outputs.<name>
        for text in _iter_expression_texts(job):
            for match in NEEDS_REF_RE.finditer(text):
                dep = match.group(1)
                if dep is None:
                    continue
                output_name = match.group(2)
                where = f"needs.{dep}" + (f".outputs.{output_name}" if output_name else "")
                if dep not in declared:
                    errors.append(
                        f"{path}: jobs.{job_name} 引用了 {where}, "
                        f"但 jobs.{job_name}.needs 里没有 {dep}"
                        + (f" (实际 needs: {declared})" if declared else " (未声明 needs)")
                    )
                    continue
                if output_name is None:
                    continue
                dep_outputs = jobs[dep].get("outputs")
                if not isinstance(dep_outputs, dict) or output_name not in dep_outputs:
                    errors.append(
                        f"{path}: jobs.{job_name} 引用了 {where}, "
                        f"但 jobs.{dep} 未声明该 output"
                    )

    return errors


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

    errors.extend(check_needs_refs(path, jobs))
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
