<div align="center">
  <img src="https://avatars.githubusercontent.com/u/245985800?s=200&v=4" alt="logo" width="100" />
  <h2>FasterEdge-TestAll</h2>
  <h3>FasterEdge 组织级综合测试与文档门禁仓库</h3>
</div>

### 一、项目简介

- FasterEdge-TestAll 集中维护 FasterEdge 组织级综合测试、全仓回归与文档一致性检查配置，作为各组件仓库的质量基线。
- 当前已启用 Markdown 文档检查门禁（`.github/workflows/docs-check.yml`），对仓库全部 `*.md` 执行 markdownlint 宽松检查，防止文档结构、链接与渲染问题进入 main。
- 仓库同时提供组织通用的 `.gitignore`、`LICENSE` 与 `SECURITY.md`，供各组件仓库按需复用；综合测试矩阵与回归清单将随各组件验收逐步补充。

### 二、CI 门禁

| 工作流 | 触发 | 检查内容 |
|---|---|---|
| `docs-check.yml` | push main / pull_request | `markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json` |

### 三、本地检查

```bash
npm install -g markdownlint-cli2
markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json
```

### 四、扩展约定

- 新增组织级测试矩阵或回归清单时，放入本仓库根目录或 `tests/`，并在 CI 中补充对应门禁。
- Markdown 风格采用宽松配置（结构/链接类规则为主），避免因排版偏好阻塞文档更新。

### 五、License

Apache-2.0，详见仓库 LICENSE。

当前版本：**1.0.20260913**
