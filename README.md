<div align="center">
  <img src="https://avatars.githubusercontent.com/u/245985800?s=200&v=4" alt="logo" width="100" />
  <h2>FasterEdge-TestAll</h2>
  <h3>FasterEdge 组织级测试与文档门禁仓库</h3>
</div>

### 一、项目简介

- FasterEdge-TestAll 集中维护 FasterEdge 组织级的**回归门禁清单**与**文档一致性检查配置**。
- 仓库已启用的门禁有两类：
  - `docs-check.yml`：对仓库全部 `*.md` 执行 markdownlint 宽松检查，防止文档结构、链接与渲染问题进入 main。
  - `regression.yml`：按 `repos.yml` 清单，对清单内各组件仓库**逐个 clone** 并执行该仓自己声明的检查命令（`go vet ./...`、`go test -count=1 ./...`、`npm ci` + `npm run build` 等）。触发方式为定时（每周一）、手动，以及**限定 paths 的 pull_request**（仅 `repos.yml` / 本 workflow / `scripts/**` 变更）。
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
3. `jobs.<job>.needs` 里列出的前置 job 必须真实存在，且不能自引用。
4. 任何 `needs.<job>.outputs.<name>` 引用都必须满足：该 job 出现在本 job 的 `needs` 里，且该前置 job 真的声明了这个 output。

第 3、4 条是静态校验 `regression.yml` 的**表达式引用链**，第 4 条为一次真实故障而加：`regression.yml` 曾写成 `matrix.include: ${{ fromJSON(needs.matrix.outputs.include) }}`，但该 job 的 `needs` 只有 `plan`（输出在 `plan.outputs.include` 定义）。YAML 合法、`needs` 本身也没拼错，`if` 里用的还是正确的 `needs.plan.outputs.include`，因此原来的校验器（只看顶层键 + `runs-on` + 脚本引用）全部放行；而 matrix 永远展开为空，整套回归门禁在 CI 上等于没跑。现在这类"能跑但等于没跑"的引用笔误会在 `lint` 阶段就失败。

### 四、CI 门禁

| 工作流 | 触发 | 检查内容 |
|---|---|---|
| `docs-check.yml` | push main / pull_request | `markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json` |
| `regression.yml` → `lint` | 每周一 03:17 UTC / 手动 / 限定 paths 的 pull_request | `python3 scripts/check_manifest.py .` + `parse_repos_test.py` + `check_manifest_test.py` |
| `regression.yml` → `plan` | 同上 | `python3 scripts/parse_repos.py repos.yml --github-output $GITHUB_OUTPUT` |
| `regression.yml` → `${{ matrix.name }}` | 由 matrix 展开，每仓一个 job | clone 后执行该仓的 `commands` |

> `regression.yml` **没有** push 触发：本仓库自身不含被检源码，push main 时回归结论不会变化，只在 `repos.yml` / workflow / `scripts/**` 变更时才需要重新展开矩阵，因此 `pull_request` 限定这三个路径。

`regression.yml` 的 `strategy.fail-fast: false`，单仓失败不会中断其余仓库；每个仓库的结论在 Checks 页独立可见。

手动触发时可只跑指定仓库：Actions → 组织级回归门禁 → Run workflow → `repos` 填 `ProxyArea,NetMap`。

### 五、本地检查

```bash
# 1) 文档检查
npm install -g markdownlint-cli2
markdownlint-cli2 '**/*.md' '#.git/**' --config .markdownlint-cli2.json

# 2) 清单与 workflow 静态校验（YAML 语法 + skip/reason 约束 + scripts 引用 + needs 引用链）
python3 scripts/check_manifest.py .

# 3) parse_repos 单测
python3 scripts/parse_repos_test.py

# 4) 在本机直接按清单跑各仓命令（不 clone，直接用本地同名目录）
#    注意：默认 PATH 里的 go 是坏掉的 mise shim，脚本会自动探测并前置 Go 安装目录
#    探测顺序：$GO_BIN > repos.yml 的 defaults.go_version 拼出的 mise 路径 > 安装根下最高版本 > PATH
python3 scripts/run_local.py --root /d/Projects/FasterEdge

# 5) 只跑部分仓库
python3 scripts/run_local.py --root /d/Projects/FasterEdge ProxyArea NetMap

# 6) 复现本机 npm 代理失败（不用干净 userconfig 顶掉 ~/.npmrc 的 127.0.0.1:7897）
python3 scripts/run_local.py --root /d/Projects/FasterEdge --no-fix-npm-proxy DontCrack-Desktop
```

`run_local.py` 与 CI 的差别只有一步：CI 会 `git clone`，本机脚本跳过 clone、直接在各仓已有的工作副本上执行同样的 `commands`。命令本身完全一致，因此本机结论可以直接推断 CI 行为。

Go 版本不写死在脚本里：脚本先读 `repos.yml` 的 `defaults.go_version`，按该版本拼出 mise 安装路径；若该版本目录不存在，则扫描安装根下所有 `go/<version>` 目录并取版本号最高的一个；都没有才回落到 PATH 上的 `go`。当前 `repos.yml` 声明 `1.27.4`，本机安装根实际只装了 `1.27.0`，因此实际命中的是 `go/1.27.0/bin`，而 `go version` 在该目录下运行时因 `go.mod` 的 `go 1.27.4` 指令与 `GOTOOLCHAIN=auto` 会自动切到已缓存的 `go1.27.4` toolchain（`go env GOVERSION` 输出 `go1.27.4`）——脚本命中哪个目录、编译实际用哪个版本，链路上都可核对，不做"看起来是 1.27.4"的假设。

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
| B2C | skip | 实测工作副本 437MB（含 `.git`；不含 `.git` 为 308MB）的上游增强分支，FVT 测试集在组织级定时门禁里耗时与失败面不可控 |

#### 6.1 未纳入清单的仓库及原因

本地 `origin` 指向 `https://github.com/FasterEdge/*` 的仓库共 **55 个**，构成为：`FasterEdge-TestAll` 自身 1 个、组织级元数据仓 `.github` 1 个、其余组件仓库 **53 个**。其中 20 个已进 `repos.yml`，**尚有 33 个组件仓库未纳入**。本节逐个说明原因，不留无说明的缺口。

统计方式（本机实测）：

```bash
# 列出 origin 指向 FasterEdge 且不在 repos.yml 里的仓库
for d in */; do d=${d%/}
  url=$(git -C "$d" remote get-url origin 2>/dev/null)
  case "$url" in *github.com/FasterEdge/*) grep -q "^  - name: $d$" repos.yml || echo "$d";; esac
done
```

未纳入的 33 个仓库按原因归为四类：

**A. 可在本机跑通、但需先确定命令口径（6 个）**

| 仓库 | 本机构建形态 | 现状 |
|---|---|---|
| `Example` | Go 模块 | `go vet` / `go test` 实测均通过，可作为最小编成入口 |
| `SimpleWebShell` | Go 模块 | 同上，`route` 包测试通过 |
| `MiniGreat-Receiver` | Go + Makefile | `go vet` / `go test` 实测通过；Makefile 目标偏部署 |
| `MiniGreat-Sender` | Go + Makefile | 同上 |
| `RTSP2Other` | Go + Makefile | `go vet` / `go test` 实测通过 |
| `SimpleWebShell-RemoteUpdate` | Go + Makefile | `go vet` / `go test` 实测通过 |

这 6 个的 `go vet ./...` + `go test -count=1 ./...` 在本机全部为 0，纳入清单不存在技术障碍；未纳入的原因是它们各自的 `Makefile`/`Dockerfile` 声明的构建/部署命令与「快速静态检查」目标不同，需要先在该仓内定义一套可缓存、耗时可控的 `commands` 再纳入，而不是直接把 `make all` 搬进组织级定时门禁。

**B. 需要本机不具备的工具链或硬件（21 个）**

| 仓库 | 缺失条件 |
|---|---|
| `MCU-Arduino-Uno-R3` / `MCU-Arduino-Uno-R4` / `MCU-ESP32` / `MCU-ESP8266` | Keil / Arduino IDE 与对应 MCU 头文件库；本机无 |
| `MCU-C51` / `MCU-CW32F003` / `MCU-CH32V003` / `MCU-STC8` / `MCU-PIC10F200` / `MCU-PMS150C` / `MCU-PY32F002A` / `MCU-PY32F003` | 各家 8/32 位 MCU 的 Keil/SDCC/PICC 工具链；本机无 |
| `FPGA-Artix7-XC7A35T` / `FPGA-Zynq-7020-ALINX` | Vivado（含 MicroBlaze / HLS 综合），体量大且需授权 |
| `RelayNode-SW2MQTT` / `RelayNode-SW2USB` | 嘉立创 EDA 专业版硬件工程 + 固件工具链；本机无 |
| `Archs` / `Document` / `PrivateDocument` | 纯文档/资料归档仓，无可执行检查命令（本仓库的 `docs-check.yml` 只作用于本仓库自身，不覆盖它们） |
| `NodeDeviceExample` | 仅含固件/刷机二进制与说明，工作树无可执行检查 |
| `EndDeviceExample` | 本地工作副本为空（`git status` 报 `No commits yet`，`git log` 报 `your current branch appears to be broken`），无内容可检查 |

**C. 有可执行命令但依赖本机缺失的重型运行时（3 个）**

| 仓库 | 形态 | 未纳入原因 |
|---|---|---|
| `ModelRunntime` | C++ / C# / Go 多语言推理示例集 | 需 libtorch / onnxruntime / TensorRT / OpenVINO 等推理后端，本机均未安装，且示例参数以 `TODO` 占位 |
| `NPURunntime` | C++ / C# / Go 多平台 NPU 示例集 | 需 Ascend CANN / MNN / RKNN / Qualcomm QNN / NCNN，本机均未安装 |
| `ModelTranslator` | Python（uv 项目） | 转换后端（torch / onnx / tensorflow / openvino / coremltools）按需安装，本机未安装任何 extra |

**D. 前端仓库，命令口径未定（3 个）**

| 仓库 | 形态 | 现状 |
|---|---|---|
| `ImageMarker` | Vite + TS + Jest | `npm test` 实测 18 套件 / 86 项全通过，`npm run build` 实测通过（`✓ built in 13.74s`） |
| `Simulator` | 纯前端离线模拟器 | `npm test` 实测 23 项全通过，`npm run build` 实测通过（`✓ built in 1.30s`） |
| `SimpleWebShell-Desktop` | Tauri + Vue 3 | 无 `test` 脚本；`npm run build`（`vue-tsc --noEmit && vite build`）实测通过（`✓ built in 689ms`），桌面壳需 Rust/Tauri 工具链，未在本轮验证 |

6 + 21 + 3 + 3 = 33，与实测缺口一致。另有两个不在 33 之列、也不需要纳入的仓库：`FasterEdge-TestAll`（本仓库，由自身 CI 自举，不自我 clone）与 `.github`（组织元数据仓，issue 模板等，无可执行检查命令）。

**纳入门槛（后续工作）**：任一仓库要进 `repos.yml`，必须先在**该仓库自己的 CI** 里定义并跑通一组耗时可控、不依赖一次性外部状态的 `commands`，再按 `skip`/`reason` 的既有约定登记。当前所有 3 个 `skip` 条目都是这样登记的，未纳入的 33 个也应遵循同一门槛，避免把"没跑过"当成"跑通了"。

### 七、验证记录

本仓库落地时的实际验证（命令与结果如实记录，均为当场实测）：

| 命令 | 结果 |
|---|---|
| `python3 scripts/check_manifest.py .` | 通过：`repos.yml: 20 个条目, skip 3 个`，`docs-check.yml: OK`、`regression.yml: OK`，末行 `全部校验通过`（退出码 0） |
| `python3 scripts/parse_repos_test.py` | 通过：`grep -c PASS` = 22，`grep -c FAIL` = 0 |
| `python3 scripts/check_manifest_test.py` | 通过：`grep -c PASS` = **14**（6 个测试函数、14 条断言），`FAIL` = 0 |
| `python3 scripts/run_local.py --root /d/Projects/FasterEdge` | **17/17 条目全部通过**（每条 2 个命令均 OK，退出码 0） |
| `python3 -c "import yaml; yaml.safe_load(...)"` | 通过：`repos.yml`、`regression.yml`、`docs-check.yml` 三个文件按 `encoding='utf-8'` 解析均成功 |

断言数为什么是 14 而不是别的数字：`check_manifest_test.py` 里 `print('PASS')` 只由 `check()` 一个辅助函数发出，因此 `grep -c PASS` 就是断言条数。先前记录写作 10 是误把 `def check(` 这个函数定义行也计入了（`grep -c PATTERN` 会数到那行文本），实际断言为 9；本轮新增 `test_needs_refs()` 的 5 条断言后为 14。

改动前的基线（同一条命令，未做任何修复）实测两轮：第一轮 **13/17**（`FasterEdge`、`ProxyArea`、`DontCrack-Manager`、`DontCrack-Desktop`），第二轮 **15/17**（只剩 `DontCrack-Manager`、`DontCrack-Desktop`）。两个时间点的差异来自其他代理正在并行改这些仓库的工作区，不是榜单本身的问题；其中 `npm` 那条每次稳定失败于本机失效代理。修复 npm 规避后再跑两轮，均为 **17/17**；上面的表格记录的是修复后的一轮。

> 本机坑位记录（已在 `scripts/run_local.py` 落实规避，不再只写在文档里）：`~/.npmrc` 把
> `proxy` / `https-proxy` 固定到已失效的 `127.0.0.1:7897`，直接 `npm ci` 报 `ECONNREFUSED`。
> `run_local.py` 现在为每条 `npm` 命令生成一份只含 `registry=https://registry.npmjs.org/` 的
> 临时 userconfig，通过 `npm_config_userconfig` 注入，不改动用户自己的 `~/.npmrc`；
> 临时文件在进程结束时删除。实测该规避生效：`npm ci` `added 53 packages, and audited 54 packages in 2s`，
> `npm run build` `✓ built in 105ms`（vite 构建耗时随机器负载波动，本轮多次实测在 105–244ms 之间），`DontCrack-Desktop` 条目转为 PASS。
> 需要复现原始失败时用 `--no-fix-npm-proxy`：实测仍是 `npm ci FAIL [71.5s]`，退出码 1。
> CI runner 没有这条代理配置，不受影响。
>
> 另有两处本机坑位已一并修掉或记录：
>
> - Windows 控制台默认 GBK，被检命令输出里的 `✓` 之类字符会让 `run_local.py` 自身抛
>   `UnicodeEncodeError` 而中断整轮回归。脚本入口现在把 stdout/stderr 重设为 UTF-8 + `errors="replace"`。
> - `DontCrack-Manager`、`FasterEdge`、`ProxyArea` 的偶发失败源于本机**其他代理正在并行修改**
>   这些仓库的工作区（`git status` 可见 `internal/supervisor/*`、`netguard.go` 等未提交改动）。
>   本轮实测遇到过两次瞬时失败：一次 `go vet` 报 `undefined: mapAttachError`（他人在改的中间态），
>   一次 `go test` 中 `SetInformationJobObject` 相关用例失败。等待数十秒后重跑即恢复，
>   最终一轮 17/17 全绿。这类失败与本仓库及其清单定义无关，不计入清单缺陷。

### 八、扩展约定

- 新增组织级回归条目时，只改 `repos.yml`；不要往 workflow 里硬编码仓库名。
- 某条命令暂时跑不通，就显式 `skip: true` + `reason`，并在修好之后把 `commands` 补上、去掉 skip。
- Markdown 风格采用宽松配置（结构/链接类规则为主），避免因排版偏好阻塞文档更新。

### 九、License

Apache-2.0，详见仓库 LICENSE。

当前版本：**1.0.20261124**
