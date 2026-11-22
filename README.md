<div align="center">
  <img src="https://avatars.githubusercontent.com/u/245985800?s=200&v=4" alt="logo" width="100" />
  <h2>FasterEdge-TestAll</h2>
  <h3>FasterEdge 组织级测试与文档门禁仓库</h3>
</div>

### 一、项目简介

- FasterEdge-TestAll 集中维护 FasterEdge 组织级的**回归门禁清单**与**文档一致性检查配置**。
- 仓库已启用的门禁有两类：
  - `docs-check.yml`：对仓库全部 `*.md` 执行 markdownlint 宽松检查，防止文档结构、链接与渲染问题进入 main。
  - `regression.yml`：按 `repos.yml` 清单，对清单内各组件仓库**逐个 clone** 并执行该仓自己声明的检查命令（`go vet ./...`、`go test -count=1 ./...`、`npm ci` + `npm run build` 等），定时（每周一）与手动触发。
- 仓库同时提供组织通用的 `.gitignore`、`LICENSE` 与 `SECURITY.md`，供各组件仓库按需复用。

### 二、为什么各组件要"clone"而不是直接引用

各组件仓库（FasterEdge、ProxyArea、NetMap……）是**相互独立的 git 仓库**，本仓库无法通过 checkout 拿到它们的代码。因此门禁采用「清单 + clone」的方式：

```text
repos.yml ──> scripts/parse_repos.py ──> GitHub matrix ──> 每仓一个 job
                                                              │
                                          git clone --depth 1 <url> <ref>
                                                              │
                                          在仓库目录下逐条执行 commands
```

`repos.yml` 是唯一声明源：新增一个组件只需加一条，不需要改 workflow。

### 三、repos.yml 条目约定

| 字段 | 说明 |
|---|---|
| `name` | 仓库名，同时用于 `https://github.com/FasterEdge/<name>.git` clone |
| `url` | clone 地址 |
| `ref` | 检出的分支或 tag；留空表示仓库默认分支 |
| `commands` | 在该仓库目录下顺序执行的命令，任一条失败即该仓判定失败 |
| `skip` | `true` 表示该条目当前不参与门禁 |
| `reason` | `skip: true` 时**必填**，说明为什么不能跑 |
| `go_version` | 该仓 `go.mod` 声明的 Go 版本，缺省取 `defaults.go_version` |

两条硬约束由 `scripts/check_manifest.py` 强制执行，写错会让 `lint` job 直接失败：

1. `skip: true` 必须写 `reason`；不允许"跳过但不说原因"。
2. 非 skip 条目必须写至少一条 `commands`；不允许占位命令。

### 四、CI 门禁

| 工作流 | 触发 | 检查内容 |
|---|---|---|
| `docs-check.yml` | push main / pull_request | `markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json` |
| `regression.yml` → `lint` | 同上 + `repos.yml`/workflow/scripts 变更 | `python3 scripts/check_manifest.py .` + `parse_repos_test.py` + `check_manifest_test.py` |
| `regression.yml` → `plan` | 同上 + 每周一 03:17 UTC + 手动 | `python3 scripts/parse_repos.py repos.yml --github-output $GITHUB_OUTPUT` |
| `regression.yml` → `${{ matrix.name }}` | 由 matrix 展开，每仓一个 job | clone 后执行该仓的 `commands` |

`regression.yml` 的 `strategy.fail-fast: false`，单仓失败不会中断其余仓库；每个仓库的结论在 Checks 页独立可见。

手动触发时可只跑指定仓库：Actions → 组织级回归门禁 → Run workflow → `repos` 填 `ProxyArea,NetMap`。

### 五、本地检查

```bash
# 1) 文档检查
npm install -g markdownlint-cli2
markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json

# 2) 清单与 workflow 静态校验（YAML 语法 + skip/reason 约束 + scripts 引用）
python3 scripts/check_manifest.py .

# 3) parse_repos 单测
python3 scripts/parse_repos_test.py

# 4) 在本机直接按清单跑各仓命令（不 clone，直接用本地同名目录）
#    注意：默认 PATH 里的 go 是坏掉的 mise shim，脚本会自动探测并前置 Go 安装目录
python3 scripts/run_local.py --root /d/Projects/FasterEdge

# 5) 只跑部分仓库
python3 scripts/run_local.py --root /d/Projects/FasterEdge ProxyArea NetMap
```

`run_local.py` 与 CI 的差别只有一步：CI 会 `git clone`，本机脚本跳过 clone、直接在各仓已有的工作副本上执行同样的 `commands`。命令本身完全一致，因此本机结论可以直接推断 CI 行为。

### 六、当前清单状态

`repos.yml` 共 20 个条目，其中 **17 个参与门禁**，3 个显式 `skip`（原因写在 `repos.yml` 对应条目的 `reason` 字段，摘要见下）。

| 仓库 | 状态 | 说明 |
|---|---|---|
| FasterEdge / ProxyArea / NetMap / FasterEdge2Api / DontCrack-Manager | 参与 | `go vet` + `go test` |
| DontCrack4Windows / 4Mac / 4ManyLinux / 4OpenHarmony / 4AndroidLinuxKernelSide | 参与 | 同上 |
| Any2UTF8 / Any2Pcd / FasterEdgeDoctor / MqttBroker / MqttBrokerCore / SimpleTimeService | 参与 | 同上 |
| DontCrack-Desktop | 参与 | `npm ci` + `npm run build` |
| FasterEdgeOS | skip | 需 Linux 构建主机与 GNU make；本机不具备内核/glibc 构建条件 |
| TsnHub | skip | 需 Conan 2.x + open62541 1.5；本机无 conan/open62541，且当前工作区有编译失败的未提交改动（属该仓范围） |
| B2C | skip | 324MB 上游增强分支，FVT 测试集在组织级定时门禁里耗时与失败面不可控 |

### 七、验证记录

本仓库落地时的实际验证（命令与结果如实记录）：

| 命令 | 结果 |
|---|---|
| `python3 scripts/check_manifest.py .` | 通过：`repos.yml: 20 个条目, skip 3 个`，两个 workflow 均 OK |
| `python3 scripts/parse_repos_test.py` | 通过：22 项断言全 PASS |
| `python3 scripts/check_manifest_test.py` | 通过：10 项断言全 PASS |
| `python3 scripts/run_local.py --root /d/Projects/FasterEdge` | **17/17 条目全部通过**（每条 2 个命令均 OK） |
| `python3 -c "import yaml; yaml.safe_load(...)"` | 通过：`repos.yml` 与两个 workflow 均可被 YAML 解析 |

> 本机坑位记录（已在 `repos.yml` 对应条目注释，不属于清单问题）：`~/.npmrc` 把
> `proxy` 固定到已失效的 `127.0.0.1:7897`，直接 `npm ci` 报 `ECONNREFUSED`。
> 用干净的 `npm_config_userconfig` 指向 `registry.npmjs.org` 后，`npm ci`
> （`added 53 packages in 3s`）与 `npm run build`（`✓ built in 152ms`）均通过。
> CI runner 没有这条代理配置，不受影响。

### 八、扩展约定

- 新增组织级回归条目时，只改 `repos.yml`；不要往 workflow 里硬编码仓库名。
- 某条命令暂时跑不通，就显式 `skip: true` + `reason`，并在修好之后把 `commands` 补上、去掉 skip。
- Markdown 风格采用宽松配置（结构/链接类规则为主），避免因排版偏好阻塞文档更新。

### 九、License

Apache-2.0，详见仓库 LICENSE。

当前版本：**1.0.20261116**
