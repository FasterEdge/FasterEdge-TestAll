<div align="center">
  <img src="https://avatars.githubusercontent.com/u/245985800?s=200&v=4" alt="logo" width="100" />
  <h2>FasterEdge-TestAll</h2>
  <h3>FasterEdge Organization-Level Integrated Test and Docs Gate Repository</h3>
</div>

### 1. Introduction

- FasterEdge-TestAll centrally maintains the FasterEdge organization-level integrated tests, full-repo regression and documentation consistency check configuration, serving as the quality baseline for each component repository.
- A Markdown documentation gate (`.github/workflows/docs-check.yml`) is currently enabled, running markdownlint relaxed checks against all `*.md` files in the repository to prevent documentation structure, link and rendering issues from reaching main.
- The repository also provides organization-wide `.gitignore`, `LICENSE` and `SECURITY.md` for component repositories to reuse as needed; the integrated test matrix and regression checklist will be gradually extended as components are accepted.

### 2. CI Gate

| Workflow | Trigger | Check content |
|---|---|---|
| `docs-check.yml` | push main / pull_request | `markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json` |

### 3. Local Check

```bash
npm install -g markdownlint-cli2
markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json
```

### 4. Extension Conventions

- When adding new organization-level test matrices or regression checklists, put them in the repository root or `tests/`, and add the corresponding gate in CI.
- Markdown style uses a relaxed config (structure/link rules mainly) to avoid blocking documentation updates for formatting preferences.

### 5. License

Apache-2.0, see the repository LICENSE.

Current version: **1.0.20261022**