# ops-direct-invoke

`ops-direct-invoke` 提供直调算子的需求对齐、方案设计、实现、功能验收、代码检视和交付文档流程。插件名称、安装 ID 与入口 Skill 名称统一为 `ops-direct-invoke`。

**调度交给 harness，知识交给 Skill，Workflow 专注于流程。** 工作区 PM 按用户的实际目标规划子 Agent 合作，通过 harness 执行 workflow YAML。算子需求对齐时必须加载 `repo-requirement` Skill，按其中的要求执行；算子开发时必须加载 `ops-direct-invoke` Skill，按其中的要求执行。每个 task 同时声明执行与验收；运行期派发、并行及同节点重试使用框架原生机制。

## 安装与入口

需要 Node.js 20.11+、Python 3、PyYAML、已安装的 Agent CLI、支持 procedure 字段的 workflow-orchestrator，以及用于默认后台启动的 tmux。源码仓需初始化 `vendor/cannbot-skills`。在 cannbot 根目录执行：

```bash
node script/bin/cannbot.js install ops-direct-invoke \
  --source "$PWD" \
  --tool codex --target /absolute/operator-repo
```

安装器按 `ops-direct-invoke` 定位官方插件目录。也可在本插件目录执行 `bash init.sh project codex /absolute/operator-repo`。目前验证的客户端为 opencode、codex、claude。源码安装把 Skill 链接到源目录，打包安装复制完整 Skill 资源；角色资产安装在目标仓中。子仓可用 `--override-skills /absolute/overrides` 覆盖已有的 `repo-*` Skill，入口及调度 Skill 不在覆盖范围内。

插件的 [AGENTS.md](AGENTS.md) 是常驻工作区的通用 PM 指引，直接描述需求拆解、子 Agent 协作、工作流启动与多轮交付，不再通过 PM 角色文件转接。初始化时，安装器将其正文写入工作区 `AGENTS.md` 的插件管理区块，保留用户原有内容；Claude 使用 `CLAUDE.md`。重复初始化替换同一管理区块，不重复追加。

算子开发任务由 PM 加载 `ops-direct-invoke` Skill，按其中的要求执行。所有子 Agent 必须在 Workflow YAML 落盘后由 harness 拉起。`agents/` 只保留 architect、developer、verifier 三个子 Agent，分别安装为 Codex 的 TOML 或 OpenCode、Claude 的 Markdown 角色配置。

每个任务、每轮 Workflow 独立存放 YAML 和运行记录：

```text
.cannbot/任务1/
├── workflow1/
│   ├── workflow1.yaml
│   ├── 需求与交付件
│   └── .workflow/
└── workflow2/
    ├── workflow2.yaml
    ├── 本轮输入与交付件
    └── .workflow/
```

仓库首次环境检查结果存放在 `.cannbot/环境信息.md`，检查日志存放在 `.cannbot/环境检查/`。后续算子开发直接复用已有通过记录，不重复探测环境；每轮复制为 `work_dir/环境信息.md`，运行中只读。

当前 Workflow 目录的绝对路径即 `work_dir`。首轮未满足交付要求时，PM 根据缺口规划下一轮，保留旧 YAML、状态及验收证据。下一轮明确引用或复制有效输入，并重新验收受影响交付件；同一轮中断恢复则沿用原目录和原 YAML。

## 从需求到执行

- 需求对齐：必须加载 [repo-requirement](skills/repo-requirement/SKILL.md) Skill，按其中的要求执行。
- 启动前环境检查由 PM 负责：必须加载 [repo-env-check](skills/repo-env-check/SKILL.md) Skill，按其中的要求执行。
- 算子开发：必须加载 [ops-direct-invoke](skills/ops-direct-invoke/SKILL.md) Skill，按其中的要求执行。
- Workflow 执行：必须加载 [workflow-orchestrator](../../harness/workflow-orchestrator/SKILL.md) Skill，按其中的要求执行。

## 默认流程与角色

需求确认与 PM 环境检查在工作流启动前完成。PM 先核对路线依据和 Skill 调用契约；路线明确时使用 basic，有关键实现疑点时先独立运行 [feasibility](skills/ops-direct-invoke/workflows/ascendc/feasibility.yaml)。穿刺交付最小代码、代表用例的真实编译与设备证据，通过后新开一轮 basic；规则冲突先澄清，不靠穿刺绕过。basic 默认包含 7 个普通节点，知识搜集可以省略或用前轮资料替代；仓内没有已有算子文档时，下发前从本轮图省略最后的文档准备节点：

```mermaid
flowchart TD
    K[0.0 知识搜集] --> T[1 测试工程开发]
    B[0.1 黑盒测试设计] --> T
    T --> D[2 算子开发]
    D --> W[3 白盒测试设计与用例接入]
    W --> R[4 代码修复]
    R --> U[5 文档准备：仅仓内已有算子文档时]
```

知识搜集形成中立补充文档，包含资料索引、API 组合和不同 shape 的初版 Tiling 草稿，开发可根据验证调整实现。算子开发通过 `knowledge_documents` 接收本轮或前轮文档路径；无资料时使用默认值“无补充文档。”，不要求工作流存在知识搜集节点。省略知识节点时删去相应依赖，将黑盒设计编号改为 `0`、测试工程依赖改为 `0`，同步更新知识文档变量，其他阶段仍为 `1`～`5`。测试工程先准备黑盒，算子实现后再按源码生成白盒用例并直接接入已有框架。白盒节点检查测试质量与证据，发现的算子缺陷交给默认编排的代码修复节点；代码修复要求全量黑盒、白盒回归及代码检视通过，没有缺陷且已有当前版本的有效全量证据时复用并记录依据，不强制重复构建或测试；证据缺失或失效时补齐验证。

[generate_workflow_guide.py](skills/ops-direct-invoke/scripts/generate_workflow_guide.py) 扫描模板并生成本轮 `workflow-guide.csv`，列出模板文件名和调用时机。PM 先生成并读取引导，再打开匹配模板。调用时机由各模板第二行的 `use_when` 维护，组装后不传给 harness。basic 与 feasibility 各自维护引用图，每个节点声明 id、task YAML、depends_on、max_retries，以及 task 需要的 variables 赋值。task 内容由组装脚本读取并展开，默认每个节点允许 3 次重试（含首次执行最多 4 轮），重试次数由 PM 在下发时确定。固定必需 Skill 保留在 task；PM 仅对声明了 `executor_skills`、`verifier_skills` 的 task 下发专项必需项，以及开发、修复阶段的有限候选清单与触发条件。节点按实际证据选用候选并记录依据，必需能力缺口或已确认约束、范围变更需求写入报告，交付标准无法满足时验收失败。运行中不与 PM 或用户交互；PM 在整轮退出后处理阻塞及知识搜集建议，供下一轮编排使用，不修改已启动的 YAML。文档准备只按仓内已有格式补全资料，无已有算子文档时直接省略节点，不创建新的文档要求。入口 [SKILL.md](skills/ops-direct-invoke/SKILL.md) 规定模板选择与使用方法。

| 角色 | 职责 |
|---|---|
| [工作区 PM](AGENTS.md) | 理解用户目标、规划协作与多轮交付；不进入 task 图 |
| [ops-direct-invoke-architect](agents/ops-direct-invoke-architect.md) | 知识搜集与黑盒方案设计 |
| [ops-direct-invoke-developer](agents/ops-direct-invoke-developer.md) | 代码开发、调试、构建与本阶段测试执行、文档编写 |
| [ops-direct-invoke-verifier](agents/ops-direct-invoke-verifier.md) | 各节点证据审核与代码检视，不重复构建或运行测试 |

节点通过 `executor` / `verifier` 名称引用安装后的客户端角色，不在 prompt 中额外读取角色文件。工作区常驻指引与运行期子 Agent 派发是两个层次；实际 provider 是否正确加载角色、Skill 和权限仍需真实调用验证。

执行者提供原始构建日志、本阶段测试结果（穿刺代表用例、正式交付全量）、源码/测试/构建产物哈希及实际加载路径，使用 [测试执行记录模板](skills/ops-direct-invoke/templates/测试执行记录.md)。验收者核对证据是否真实、完整、对应当前版本并独立检视代码；证据不足则失败，不代跑测试补证据。所有节点均按 [验收报告模板](skills/ops-direct-invoke/templates/验收报告.md) 生成 `<节点ID>-验收报告.md`，其中记录结论及具体修改意见。共享 acceptance 只列执行者交付件；验收报告由 verifier 在 procedure 中生成并检查，executor 根据回传反馈按需读取详情，不代写或等待它。

穿刺代码、测试入口及证据通过本轮任务 prompt 传入下一轮，并明确使用节点，知识资料通过 `knowledge_documents` 传入；记录绝对路径、版本及适用范围，复用有效产物而非重复调查。穿刺通过仅证明限定范围可行，正式交付仍须全量测试和代码检视。

报告保留关键结论和证据路径，每次真实执行的输入/版本清单、原始日志与用例明细只存一份；后续节点引用并核对差异，每个验收者仍独立出具本阶段报告。返工依据 harness 回传的失败摘要，按需读取所引用报告的未解决项，并补充变更证据；版本变化使旧证据失效时重新验证。确定性阻塞未变时只记录条件复核，当前 harness 仍按预算重试，不能凭报告自动跳过重试。

固定绑定采用与当前节点契约兼容的仓库能力：工程骨架由 `repo-op-templates` 承担，白盒方法由 `repo-test-develop` 承担。`ascendc-direct-invoke-template` 和 `ascendc-whitebox-design` 不再是默认任务的固定项；安装可用不等于必须调用。PM 为补充项核对完整契约，不向禁止交互和派发的节点绑定仍要求这些操作的 Skill，也不靠局部豁免后强行调用。

公共 Skill 的规则由来源仓维护；本插件只调整绑定与流程，不复制或覆盖其规则。已知 Ascend 950 路由组合问题见 [cannbot-skills #688](https://gitcode.com/cann/cannbot-skills/issues/688)。

## 目录与接口

```text
ops-direct-invoke/
├── AGENTS.md                       # 工作区 PM 的通用指引
├── README.md                       # 使用方式与当前设计
├── test/ut/
│   ├── test_all.py                  # 自动执行所有测试类型
│   ├── support.py                   # CLI 与 YAML 检查共用工具
│   ├── workflow_guide/test.py
│   ├── retry_feedback/test.py
│   ├── variables/test.py
│   ├── workflow_generation/test.py
│   └── workflow_execution/test.py
├── agents/                         # architect / developer / verifier
├── init.sh                         # 统一安装器的薄入口
├── plugin-sources.json             # 公共 Skill 来源与安装方式
├── plugin-install.json             # 外部依赖仓声明
└── skills/
    ├── repo-env-check/             # PM 的启动前环境检查
    ├── repo-requirement/
    │   ├── SKILL.md
    │   └── references/requirement-checklist.md
    ├── ops-direct-invoke/
    │   ├── SKILL.md                 # 先生成引导，再选用模板
    │   ├── scripts/
    │   │   ├── generate_workflow_guide.py
    │   │   ├── assemble_workflow.py
    │   │   └── run_workflow.py
    │   ├── tasks/
    │   │   ├── ascendc/             # <步骤名>.yaml，不带编号
    │   │   └── common/
    │   ├── workflows/
    │   │   └── ascendc/
    │   │       ├── basic.yaml       # 正式开发，含 use_when
    │   │       └── feasibility.yaml # 独立技术穿刺，含 use_when
    │   └── templates/              # 文档模板平铺，文件名不带编号
    ├── repo-knowledge/
    ├── repo-build-guide/
    ├── repo-op-templates/
    ├── repo-coding-rules/
    └── repo-test-develop/
```

## 任务、模板与运行接口

必须加载 [ops-direct-invoke](skills/ops-direct-invoke/SKILL.md) Skill，按其中的要求执行。

- [任务定义](skills/ops-direct-invoke/tasks/)
- [引导生成脚本](skills/ops-direct-invoke/scripts/generate_workflow_guide.py)
- [文档模板](skills/ops-direct-invoke/templates/)
- [组装脚本](skills/ops-direct-invoke/scripts/assemble_workflow.py)
- [启动脚本](skills/ops-direct-invoke/scripts/run_workflow.py)

## 知识与范围

Skill 正文及 references 仅包含自身职责，不互相调用或路由；跨 Skill 组合由 PM 或 task 的 approach/procedure 显式声明。引用处只保留加载条件、Skill 名称及按其要求执行，不复制内部步骤或规则。节点输入、产物路径和验收结果由 task 声明；资源目录引用用于定位文件，不代表调用其所属 Skill。公共领域 Skill 来自 vendor，harness 和统一安装器作为公共基础设施使用。

角色、task、脚本、仓库知识及交付模板均由本插件独立维护，安装与运行使用本目录声明的资产及公共依赖。

本仓 `repo-*` 知识按 CANN Bench 的直调工程与评测契约组织，包含需求、环境、接口、模板、构建、测试和编码规则。初始化会获取 `cann-bench` 到 `.cannbot/dependencies/ops-direct-invoke/cann-bench/`，实际运行记录所用 commit；已有 checkout 可作为任务输入复用。跨仓定制继续通过同名 `repo-*` Skill 覆写，不将仓库知识复制进 task。

当前范围为本地开发、功能验收与交付文档，不包含性能采集、性能迭代及回归复核、性能验收、回顾、经验总结、PR、外部 CI 或合并。需求阶段仍需如实记录性能诉求；用户要求的硬门槛超出当前执行范围时，先对齐交付安排，不能承诺本流程已验证性能。引用业务知识时不启用其中遗留的 PM 派发、状态维护或回退指令。

## 已知限制与验证

harness 按黑盒使用，只通过公开 CLI 调用并检查输出。已验证同节点重试及失败阻断；重试耗尽后直接重启相同 work_dir 不能清除耗尽状态。

Codex provider 的 CLI 替身黑盒测试覆盖验收裁决与重试反馈：verifier 按框架提示调用公开裁决命令提交 pass/fail，失败原因进入下一次执行提示词；落盘的验收报告保留且下一次执行可读。反馈处理统一在角色中约定，task 保留具体业务步骤与报告交付要求。此测试验证 CLI 传参、裁决命令和报告可访问性，不证明真实模型的遵从性，也不代表其他 provider 行为。

以下能力尚无本流程已验证的完整公开契约：跨节点返工、下游结果失效、运行中问卷等待与恢复。需求问卷在启动前解决；运行中不发问卷或等待 PM。必要输入或确认缺失时记录阻塞，验收失败按 harness 既定重试与耗尽策略处理；PM 在整轮退出后读取结果并组织下一轮，不自行改状态或用私有脚本补齐框架能力。

工作流 UT 位于 test/ut/，各测试类型统一以 test.py 为入口。test_all.py 自动发现直接子目录的 test.py，执行全部类型并汇总；任一类型失败、缺少入口或没有测试类型时返回非零退出码。新增类型沿用此目录约定即可纳入总入口。

在 cannbot 根目录运行所有工作流 UT：

```bash
python3 plugins-official/ops-direct-invoke/test/ut/test_all.py
```

可从任意目录调用；测试使用临时工作目录，结束后自动清理。依赖 Python 3.9+、PyYAML 和本仓公共 harness，使用前台模拟执行，不需要 tmux、真实 Agent CLI 或 NPU。harness 位于其它位置时传 `--harness-skill /absolute/workflow-orchestrator`，总入口会透传给每个测试类型。单独执行某类时使用相同参数约定，例如：

```bash
python3 plugins-official/ops-direct-invoke/test/ut/workflow_execution/test.py
```

| 测试类型 | 看护内容 |
|---|---|
| retry_feedback | 真实 harness 公开 CLI 配合 Codex 替身，验证失败→重试→通过、失败摘要和报告路径自动回传、按回传路径读取完整意见；不调用真实模型 |
| workflow_guide | 引导覆盖全部模板且场景与模板一致；新增、删除、修改后重新生成；非法场景拒绝；图与 task 引用有效 |
| workflow_generation | 遍历引导条目，调用 assemble_workflow.py 生成临时 workflow.yaml；检查顶层及节点字段、类型、字符串 ID 和依赖图，并与引用图、下发预算及原始 task 逐项比对 |
| variables | 默认值与必填校验、节点隔离、多行文本及字面替换；拒绝未知变量、非法声明和空提示项 |
| workflow_execution | 对每个引导条目分别调用 run_workflow.py --template 和 --yaml，后者使用本轮生成的 workflow.yaml；通过 harness --dry-run 验证退出码为 0、预期节点全部通过，且引用模板未被修改、完整 YAML 已落盘并可用于恢复 |

各项测试通过脚本动态生成引导并读取，不依赖手工注册表。新增工作流自动接受相同检查。执行测试只能证明标准 YAML 被框架接受且模拟调度能完成，不证明真实 Agent 执行、业务验收或 NPU 实测通过。测试只通过公开 CLI 与落盘状态观察 harness，不读取内部脚本实现。

安装与打包集成检查仍可在 cannbot 根目录运行：

```bash
npm --prefix script run build:plugins
node --test script/test/harness.test.js
npm --prefix script run pack:smoke
```

检查覆盖源码与打包安装、工作区 PM 指引与重复初始化、客户端角色配置、引导生成与模板资源、模板与 task 一致性、引用模板展开及完整 YAML 两种启动方式、外部 task 与不同顺序组装、并行汇合、成功路径、同节点重试、验收失败阻断、耗尽后重启、多轮 Workflow 状态隔离、前后台参数与退出结果，以及独立源码布局下的安装运行。实际 npm 包还会安装后直接选择内置模板并模拟执行。格式与模拟检查不证明问卷交互、真实 provider 角色权限或 NPU 功能实测已经通过。
