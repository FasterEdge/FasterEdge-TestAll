<div align="center">
  <img src="https://avatars.githubusercontent.com/u/245985800?s=200&v=4" alt="logo" width="100" />
  <h2>FasterEdge-TestAll</h2>
  <h3>FasterEdge Organization-Level Test and Docs Gate Repository</h3>
</div>

### 1. Introduction

- FasterEdge-TestAll maintains the FasterEdge organization-level **regression manifest** and the **documentation consistency gate**.
- Two gates are active:
  - `docs-check.yml`: runs relaxed markdownlint over every `*.md` in this repository, preventing structural, link and rendering regressions from reaching main.
  - `regression.yml`: reads `repos.yml`, **clones each listed component repository** and runs the check commands that repository declares (`go vet ./...`, `go test -count=1 ./...`, `npm ci` + `npm run build`, ...). Triggered on schedule (every Monday) and manually.
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

### 4. CI Gates

| Workflow | Trigger | Check |
|---|---|---|
| `docs-check.yml` | push main / pull_request | `markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json` |
| `regression.yml` → `lint` | same, plus `repos.yml`/workflow/scripts changes | `python3 scripts/check_manifest.py .` + `parse_repos_test.py` + `check_manifest_test.py` |
| `regression.yml` → `plan` | same, plus Mondays 03:17 UTC, plus manual | `python3 scripts/parse_repos.py repos.yml --github-output $GITHUB_OUTPUT` |
| `regression.yml` → `${{ matrix.name }}` | expanded per repository | clone, then run that repository's `commands` |

`regression.yml` sets `strategy.fail-fast: false`, so one failing repository does not abort the others, and each repository reports its own result in the Checks page.

Manual runs can target a subset: Actions → organization regression gate → Run workflow → put `ProxyArea,NetMap` into `repos`.

### 5. Local Checks

```bash
# 1) Documentation gate
npm install -g markdownlint-cli2
markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json

# 2) Manifest and workflow validation (YAML syntax + skip/reason rules + script refs)
python3 scripts/check_manifest.py .

# 3) Unit tests for the manifest parser
python3 scripts/parse_repos_test.py

# 4) Run the manifest commands locally against existing working copies (no clone)
python3 scripts/run_local.py --root /d/Projects/FasterEdge

# 5) Subset only
python3 scripts/run_local.py --root /d/Projects/FasterEdge ProxyArea NetMap
```

`run_local.py` differs from CI in one step only: CI clones the repository, while the local script runs the same `commands` on the existing working copy. The commands themselves are identical, so local results carry over to CI.

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
| B2C | skip | 324MB upstream fork; the FVT suite is too slow and too flaky for an organization-level scheduled gate |

### 7. Verification record

Results actually obtained while landing this change:

| Command | Result |
|---|---|
| `python3 scripts/check_manifest.py .` | pass: `repos.yml: 20 个条目, skip 3 个`, both workflows OK |
| `python3 scripts/parse_repos_test.py` | pass: all 22 assertions |
| `python3 scripts/check_manifest_test.py` | pass: all 10 assertions |
| `python3 scripts/run_local.py --root /d/Projects/FasterEdge` | **17 of 17 entries fully green** (both commands per entry) |
| `python3 -c "import yaml; yaml.safe_load(...)"` | pass: `repos.yml` and both workflows parse |

> Local environment note (also recorded in the `repos.yml` entry; not a manifest
> problem): `~/.npmrc` pins `proxy` to the dead `127.0.0.1:7897`, so a bare
> `npm ci` reports `ECONNREFUSED`. With a clean `npm_config_userconfig` pointing
> at `registry.npmjs.org`, both `npm ci` (`added 53 packages in 3s`) and
> `npm run build` (`✓ built in 152ms`) pass. CI runners do not carry that proxy.

### 8. Extension Conventions

- Add organization-level regression entries by editing `repos.yml` only; never hard-code repository names into the workflow.
- If a command cannot run yet, set `skip: true` plus a `reason`, and fill in `commands` and drop the skip once it can.
- Markdown style stays relaxed (structure/link rules mainly) to avoid blocking documentation updates over formatting preferences.

### 9. License

Apache-2.0, see the repository LICENSE.

Current version: **1.0.20261116**
