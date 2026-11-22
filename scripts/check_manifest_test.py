#!/usr/bin/env python3
"""scripts/check_manifest.py 的最小测试。

覆盖:
  1. 缺 name / on / jobs 的 workflow 被判定为失败;
  2. job 既无 runs-on 也无 uses 被判定为失败;
  3. 引用了不存在的 scripts/*.py 被判定为失败(防止 workflow 引用幻影脚本);
  4. `paths: [scripts/**]` 这类通配符不被当成脚本路径(避免误报);
  5. 本仓库真实的 workflow 与 repos.yml 全部通过校验。

运行: python3 scripts/check_manifest_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from check_manifest import check_script_refs, check_workflow  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, label: str) -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        FAILURES.append(label)


def write(directory: str, name: str, text: str) -> str:
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


GOOD_WORKFLOW = """\
name: '示例'
on:
  workflow_dispatch:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: python3 scripts/parse_repos.py repos.yml
"""


def test_missing_keys() -> None:
    print("缺顶层键的 workflow 被拒绝")
    with tempfile.TemporaryDirectory() as tmp:
        errors = check_workflow(write(tmp, "no-name.yml", "on: {}\njobs: {}\n"))
        check(any("name" in err for err in errors), f"缺 name 被点名: {errors}")

        errors = check_workflow(write(tmp, "no-jobs.yml", "name: x\non: {}\n"))
        check(any("jobs" in err for err in errors), f"缺 jobs 被点名: {errors}")

        errors = check_workflow(write(tmp, "no-on.yml", "name: x\njobs:\n  a:\n    runs-on: x\n"))
        check(any("on" in err for err in errors), f"缺 on 被点名: {errors}")


def test_job_without_runner() -> None:
    print("job 必须声明 runs-on 或 uses")
    with tempfile.TemporaryDirectory() as tmp:
        text = "name: x\non: {}\njobs:\n  a:\n    steps:\n      - run: true\n"
        errors = check_workflow(write(tmp, "bad-job.yml", text))
        check(any("runs-on" in err for err in errors), f"无 runner 的 job 被点名: {errors}")


def test_broken_yaml_is_reported() -> None:
    print("YAML 语法错误被报告")
    with tempfile.TemporaryDirectory() as tmp:
        errors = check_workflow(write(tmp, "broken.yml", "name: x\n  jobs: [\n"))
        check(len(errors) == 1 and "YAML" in errors[0], f"语法错误: {errors}")


def test_script_refs() -> None:
    print("scripts 引用校验")
    with tempfile.TemporaryDirectory() as tmp:
        path = write(tmp, "wf.yml", GOOD_WORKFLOW)
        check(check_script_refs(path, tmp) != [], "缺失脚本被识别")

        os.makedirs(os.path.join(tmp, "scripts"), exist_ok=True)
        write(tmp, os.path.join("scripts", "parse_repos.py"), "")
        check(check_script_refs(path, tmp) == [], "脚本存在时不报错")

        glob_path = write(tmp, "glob.yml", "name: x\non:\n  pull_request:\n"
                                           "    paths:\n      - 'scripts/**'\n")
        check(check_script_refs(glob_path, tmp) == [], "通配符不被当成文件路径")


def test_real_repository_manifests() -> None:
    print("本仓库真实清单通过校验")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    from check_manifest import main as check_main

    rc = check_main(["check_manifest.py", root])
    check(rc == 0, f"check_manifest 退出码 0 (实际 {rc})")


def main() -> int:
    test_missing_keys()
    test_job_without_runner()
    test_broken_yaml_is_reported()
    test_script_refs()
    test_real_repository_manifests()

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
