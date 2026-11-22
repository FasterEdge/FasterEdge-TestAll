<div align="center">
  <img src="https://avatars.githubusercontent.com/u/245985800?s=200&v=4" alt="logo" width="100" />
  <h2>FasterEdge-TestAll</h2>
  <h3>FasterEdge Organization-Level Test and Docs Gate Repository</h3>
</div>

### 1. Introduction

- FasterEdge-TestAll maintains the FasterEdge organization-level **regression manifest** and the **documentation consistency gate**.
- Two gates are active:
  - `docs-check.yml`: runs relaxed markdownlint over every `*.md` in this repository, preventing structural, link and rendering regressions from reaching main.
  - `regression.yml`: reads `repos.yml`, **clones each listed component repository** and runs the check commands that repository declares (`go vet ./...`, `go test -count=1 ./...`, `npm ci` + `npm run build`, ...). Triggers: schedule (every Monday), manual dispatch, and a **path-filtered pull_request** (only `repos.yml` / this workflow / `scripts/**`). There is no `push` trigger.
- The repository also ships the organization-wide `.gitignore`, `LICENSE` and `SECURITY.md` for component repositories to reuse.

### 2. Why components are cloned instead of checked out

Each component repository (FasterEdge, ProxyArea, NetMap, ...) is an **independent git repository**, so this repository cannot check them out. The gate therefore works from a manifest:

```text
repos.yml ──> scripts/parse_repos.py ──> GitHub matrix ──> one job per repository
                                                                │
                                            git clone --depth 1 <url> <ref>
                                                                │
                                       run each `commands` entry inside the repo
```

`repos.yml` is the single source of truth: adding a component is one entry, not a workflow edit.

### 3. repos.yml entry schema

| Field | Meaning |
|---|---|
| `name` | Repository name, also used to build `https://github.com/FasterEdge/<name>.git` |
| `url` | Clone URL |
| `ref` | Branch or tag to check out; empty means the default branch |
| `commands` | Commands run sequentially inside that repository; any failure fails the entry |
| `skip` | `true` marks the entry as not gated yet |
| `reason` | **Required** when `skip: true`; explains why it cannot run |
| `go_version` | Go version declared by that repository's `go.mod`; defaults to `defaults.go_version` |

Two hard rules are enforced by `scripts/check_manifest.py`, and violating them fails the `lint` job:

1. `skip: true` must carry a `reason` — silently skipping is rejected.
2. A non-skipped entry must declare at least one `commands` item — placeholder commands are rejected.
3. Every predecessor listed in `jobs.<job>.needs` must exist, and a job cannot depend on itself.
4. Every `needs.<job>.outputs.<name>` reference must satisfy both: that job appears in the current job's `needs`, and that predecessor really declares the output.

Rules 3 and 4 statically validate the **expression reference chain** of `regression.yml`. Rule 4 exists because of a real incident: `regression.yml` once read `matrix.include: ${{ fromJSON(needs.matrix.outputs.include) }}` while that job's `needs` contained only `plan` (the output is defined as `plan.outputs.include`). The YAML was valid, `needs` itself was spelled correctly, and the job-level `if` used the correct `needs.plan.outputs.include` — so the previous checker (top-level keys + `runs-on` + script references) passed it. The matrix expanded to empty and the entire regression gate silently did not run. Such "runs but does nothing" reference typos now fail at `lint`.

### 4. CI Gates

| Workflow | Trigger | Check |
|---|---|---|
| `docs-check.yml` | push main / pull_request | `markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json` |
| `regression.yml` → `lint` | Mondays 03:17 UTC / manual / path-filtered pull_request | `python3 scripts/check_manifest.py .` + `parse_repos_test.py` + `check_manifest_test.py` |
| `regression.yml` → `plan` | same | `python3 scripts/parse_repos.py repos.yml --github-output $GITHUB_OUTPUT` |
| `regression.yml` → `${{ matrix.name }}` | expanded per repository | clone, then run that repository's `commands` |

> `regression.yml` has **no** `push` trigger. This repository contains none of the gated source, so a push to `main` cannot change a regression conclusion; the matrix only needs re-expanding when `repos.yml`, this workflow, or `scripts/**` change, which is why `pull_request` is filtered to those three paths.

`regression.yml` sets `strategy.fail-fast: false`, so one failing repository does not abort the others, and each repository reports its own result in the Checks page.

Manual runs can target a subset: Actions → organization regression gate → Run workflow → put `ProxyArea,NetMap` into `repos`.

### 5. Local Checks

```bash
# 1) Documentation gate
npm install -g markdownlint-cli2
markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json

# 2) Manifest and workflow validation (YAML syntax + skip/reason rules + script refs + needs chain)
python3 scripts/check_manifest.py .

# 3) Unit tests for the manifest parser
python3 scripts/parse_repos_test.py

# 4) Run the manifest commands locally against existing working copies (no clone)
#    The Go toolchain is probed, never hard-coded:
#    $GO_BIN > mise path built from repos.yml defaults.go_version > highest version
#    under the install root > go on PATH
python3 scripts/run_local.py --root /d/Projects/FasterEdge

# 5) Subset only
python3 scripts/run_local.py --root /d/Projects/FasterEdge ProxyArea NetMap

# 6) Reproduce the local npm proxy failure (do not override ~/.npmrc's 127.0.0.1:7897)
python3 scripts/run_local.py --root /d/Projects/FasterEdge --no-fix-npm-proxy DontCrack-Desktop
```

`run_local.py` differs from CI in one step only: CI clones the repository, while the local script runs the same `commands` on the existing working copy. The commands themselves are identical, so local results carry over to CI.

The Go version is not hard-coded in the script. It first reads `defaults.go_version` from `repos.yml` and builds the corresponding mise path; if that version directory does not exist, it scans the install root for all `go/<version>` directories and picks the highest version number; only if neither exists does it fall back to `go` on `PATH`. `repos.yml` currently declares `1.27.4` while the local install root only has `1.27.0`, so the script lands on `go/1.27.0/bin`, and `go version` inside it reports `go1.27.4` because `GOTOOLCHAIN=auto` switches to the cached toolchain demanded by the `go 1.27.4` directive in each `go.mod` (`go env GOVERSION` → `go1.27.4`). Every hop in that chain is checkable, instead of assuming the version that "looks right".

### 6. Current manifest state

`repos.yml` holds 20 entries: **17 gated**, 3 explicitly skipped with reasons recorded in each entry's `reason` field.

| Repository | Status | Note |
|---|---|---|
| FasterEdge / ProxyArea / NetMap / FasterEdge2Api / DontCrack-Manager | gated | `go vet` + `go test` |
| DontCrack4Windows / 4Mac / 4ManyLinux / 4OpenHarmony / 4AndroidLinuxKernelSide | gated | same |
| Any2UTF8 / Any2Pcd / FasterEdgeDoctor / MqttBroker / MqttBrokerCore / SimpleTimeService | gated | same |
| DontCrack-Desktop | gated | `npm ci` + `npm run build` |
| FasterEdgeOS | skip | Needs a Linux build host and GNU make; kernel/glibc build not available here |
| TsnHub | skip | Needs Conan 2.x and open62541 1.5; neither is installed, and the current working tree has an unrelated compile failure inside that repository |
| B2C | skip | Measured 437MB working copy (including `.git`; 308MB without it), upstream fork; the FVT suite is too slow and too flaky for an organization-level scheduled gate |

#### 6.1 Repositories not in the manifest, and why

There are **55** local repositories whose `origin` points at `https://github.com/FasterEdge/*`: this repository itself, the organization metadata repository `.github`, and **53 component repositories**. Only 20 of those are in `repos.yml`, so **33 component repositories are not covered yet**. Each is accounted for below — no silent gaps.

Measurement (run locally):

```bash
for d in */; do d=${d%/}
  url=$(git -C "$d" remote get-url origin 2>/dev/null)
  case "$url" in *github.com/FasterEdge/*) grep -q "^  - name: $d$" repos.yml || echo "$d";; esac
done
```

**A. Runnable locally, command set not yet settled (6)**

| Repository | Build form | Status |
|---|---|---|
| `Example` | Go module | `go vet` / `go test` both pass locally; smallest candidate for onboarding |
| `SimpleWebShell` | Go module | same; the `route` package tests pass |
| `MiniGreat-Receiver` | Go + Makefile | `go vet` / `go test` pass locally; the Makefile targets are deployment-oriented |
| `MiniGreat-Sender` | Go + Makefile | same |
| `RTSP2Other` | Go + Makefile | `go vet` / `go test` pass locally |
| `SimpleWebShell-RemoteUpdate` | Go + Makefile | `go vet` / `go test` pass locally |

There is no technical obstacle for these six: `go vet ./...` plus `go test -count=1 ./...` exit 0 on this machine. They are not listed because their own `Makefile`/`Dockerfile` declare build and deployment commands with a different goal than a fast static check. Each needs a cacheable, time-bounded `commands` set defined inside its own repository before joining the scheduled gate — not a blind copy of `make all`.

**B. Requires toolchains or hardware not available here (21)**

| Repository | Missing requirement |
|---|---|
| `MCU-Arduino-Uno-R3` / `MCU-Arduino-Uno-R4` / `MCU-ESP32` / `MCU-ESP8266` | Keil / Arduino IDE and the matching MCU header libraries; not installed |
| `MCU-C51` / `MCU-CW32F003` / `MCU-CH32V003` / `MCU-STC8` / `MCU-PIC10F200` / `MCU-PMS150C` / `MCU-PY32F002A` / `MCU-PY32F003` | Vendor Keil/SDCC/PICC toolchains for 8/32-bit MCUs; not installed |
| `FPGA-Artix7-XC7A35T` / `FPGA-Zynq-7020-ALINX` | Vivado (including MicroBlaze / HLS synthesis); large and license-bound |
| `RelayNode-SW2MQTT` / `RelayNode-SW2USB` | JLC EDA Pro hardware project plus firmware toolchain; not installed |
| `Archs` / `Document` / `PrivateDocument` | Documentation and archive repositories with no executable check (this repository's `docs-check.yml` only covers this repository, not them) |
| `NodeDeviceExample` | Only firmware/flashing binaries and notes; nothing executable in the working tree |
| `EndDeviceExample` | The local working copy is empty (`git status` reports `No commits yet`, `git log` reports `your current branch appears to be broken`); nothing to check |

**C. Has commands but depends on heavy runtimes missing here (3)**

| Repository | Form | Why not listed |
|---|---|---|
| `ModelRunntime` | Multi-language inference examples (C++ / C# / Go) | Needs libtorch / onnxruntime / TensorRT / OpenVINO; none installed, and the examples still carry `TODO` placeholders for model paths and tensor names |
| `NPURunntime` | Multi-platform NPU examples (C++ / C# / Go) | Needs Ascend CANN / MNN / RKNN / Qualcomm QNN / NCNN; none installed |
| `ModelTranslator` | Python (uv project) | Conversion backends (torch / onnx / tensorflow / openvino / coremltools) are per-extra installs; no extra is installed here |

**D. Front-end repositories whose command set is not settled (3)**

| Repository | Form | Status |
|---|---|---|
| `ImageMarker` | Vite + TS + Jest | `npm test` measured 18 suites / 86 tests all passing; `npm run build` passes (`✓ built in 13.74s`) |
| `Simulator` | Pure front-end offline simulator | `npm test` measured 23 tests all passing; `npm run build` passes (`✓ built in 1.30s`) |
| `SimpleWebShell-Desktop` | Tauri + Vue 3 | No `test` script; `npm run build` (`vue-tsc --noEmit && vite build`) passes (`✓ built in 689ms`); the desktop shell needs the Rust/Tauri toolchain, not verified this round |

6 + 21 + 3 + 3 = 33, matching the measured gap. Two further repositories are outside the 33 and do not need to be listed: `FasterEdge-TestAll` (this repository, which bootstraps its own CI and does not clone itself) and `.github` (organization metadata such as issue templates, with no executable check).

**Onboarding rule (follow-up work):** a repository joins `repos.yml` only after a time-bounded `commands` set has been defined and run green **in that repository's own CI**, and then registered under the existing `skip`/`reason` convention. All three current `skip` entries were registered that way, and the 33 unlisted repositories should follow the same bar — "never ran" must not be reported as "passed".

### 7. Verification record

Results actually obtained while landing this change (all measured in this round):

| Command | Result |
|---|---|
| `python3 scripts/check_manifest.py .` | pass: `repos.yml: 20 个条目, skip 3 个`, `docs-check.yml: OK`, `regression.yml: OK`, last line `全部校验通过` (exit code 0) |
| `python3 scripts/parse_repos_test.py` | pass: `grep -c PASS` = 22, `grep -c FAIL` = 0 |
| `python3 scripts/check_manifest_test.py` | pass: `grep -c PASS` = **14** (6 test functions, 14 assertions), `FAIL` = 0 |
| `python3 scripts/run_local.py --root /d/Projects/FasterEdge` | **17 of 17 entries fully green** (both commands per entry, exit code 0) |
| `python3 -c "import yaml; yaml.safe_load(...)"` | pass: `repos.yml`, `regression.yml`, `docs-check.yml` all parse with `encoding='utf-8'` |

Why 14 assertions and not some other number: `check_manifest_test.py` only ever prints `PASS` from the single `check()` helper, so `grep -c PASS` is exactly the assertion count. This record previously said 10 because `grep -c PATTERN` also counts the text of the `def check(` definition line; the actual count was 9, and 5 new assertions in `test_needs_refs()` bring it to 14.

Baseline before any fix, same command, two measured runs: the first **13 of 17** (`FasterEdge`, `ProxyArea`, `DontCrack-Manager`, `DontCrack-Desktop`), the second **15 of 17** (only `DontCrack-Manager`, `DontCrack-Desktop`). The difference between those two moments came from other agents editing those repositories' working trees, not from the manifest itself; the `npm` entry failed stably on the dead local proxy every time. After the npm workaround landed, two consecutive full runs both reported **17 of 17**; the table above records one of those post-fix runs.

> Local environment note — the workaround is now **implemented in `scripts/run_local.py`**, not merely documented: `~/.npmrc` pins `proxy` / `https-proxy` to the dead `127.0.0.1:7897`, so a bare `npm ci` reports `ECONNREFUSED`. The script now writes a temporary userconfig containing only `registry=https://registry.npmjs.org/` and injects it through `npm_config_userconfig` for every `npm` command, leaving the user's `~/.npmrc` untouched and deleting the temp file on exit. Measured: `npm ci` → `added 53 packages, and audited 54 packages in 2s`, `npm run build` → `✓ built in 105ms` (vite build time drifts with machine load; repeated runs this round measured between 105ms and 244ms), and the `DontCrack-Desktop` entry flips to PASS. Use `--no-fix-npm-proxy` to reproduce the original failure: measured `npm ci FAIL [71.5s]`, exit code 1. CI runners do not carry that proxy.
>
> Two further local issues are fixed or recorded:
>
> - The Windows console defaults to GBK, so a `✓` in a gated command's output made `run_local.py` itself raise `UnicodeEncodeError` and abort the whole run. The script entry point now reconfigures stdout/stderr to UTF-8 with `errors="replace"`.
> - The intermittent failures of `DontCrack-Manager`, `FasterEdge` and `ProxyArea` come from **uncommitted work in progress by other agents** on this machine (`git status` shows `internal/supervisor/*`, `netguard.go`, ...). Two transient failures were observed this round — one `go vet` reporting `undefined: mapAttachError` (a mid-edit state), one `go test` failing around `SetInformationJobObject`. Both recovered after waiting several tens of seconds and re-running; the final pass was 17/17 green. These are unrelated to this repository or its manifest and are not counted as manifest defects.

### 8. Extension Conventions

- Add organization-level regression entries by editing `repos.yml` only; never hard-code repository names into the workflow.
- If a command cannot run yet, set `skip: true` plus a `reason`, and fill in `commands` and drop the skip once it can.
- Markdown style stays relaxed (structure/link rules mainly) to avoid blocking documentation updates over formatting preferences.

### 9. License

Apache-2.0, see the repository LICENSE.

Current version: **1.0.20261123**
