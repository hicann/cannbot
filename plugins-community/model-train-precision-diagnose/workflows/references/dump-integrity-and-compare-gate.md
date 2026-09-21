# Dump 完整性、症状可代表性与分析门禁

本契约适用于 E01/E02、E04、E08 的 statistics、md5/xor 和 tensor 采集。`dump_integrity` 与
`symptom_reproduction` 是两个独立状态：前者只回答文件是否按预期完整落盘，后者回答插桩后的运行是否仍代表原始症状。
文件完整不等于症状已经复现。只有分析集合同时满足 `dump_integrity=valid` 和
`symptom_reproduction=reproduced`，才允许运行 `compare`、`overflow_check` 或解释其结果。大型 dump 保留原位，只把检查结果写入 Case。

多节点产物进入本契约前还必须通过
[多节点诊断作业执行、产物汇集与分析门禁](cluster-execution-and-artifact-plane.md)：执行证据完整、所有生产者停止写入、产物来自单一
run/attempt 且 `collection_state=complete`。该状态不能由文件数量或 `dump_integrity` 反推。

## 1. 采集前建立预期矩阵和复现判据

从已批准的采集配置和启动拓扑记录两侧各自的预期范围。下文 `Producer` 在分布式运行中表示 global Rank；在已确认没有分布式 Rank
的单进程/单卡运行中表示进程角色，并在采集后绑定实际 `proc<PID>`：

- Run、Node、Step 和 Producer；`rank: []` 按本次作业实际参与 Rank 展开，显式 Rank 列表按列表展开；非分布式运行预先记录
  预期进程数量和角色，采集后补充 PID；
- 唯一 attempt、execution/scheduler mode、Job ID 或 handoff 回传、生产者 Node × Producer 矩阵和共享产物根；
- `task`、`summary_mode`、`level`、`scope`/`list`、forward/backward/optimizer 边界；
- 预期落盘根目录及 target/golden 或 run A/run B 身份；
- 不依赖待执行 compare/overflow_check 结果的症状信号、原始复现窗口和等价判据，例如对齐日志、显式有限性检查、原始报错，
  或完整 `dump.json` 中直接记录的非有限统计。

分布式运行未确认 world size、Rank 映射或目标 Step，或非分布式运行未确认预期进程角色/数量或目标 Step 时，`dump_integrity` 只能
是 `unknown`。未预先声明症状信号、对齐口径或等价窗口时，
`symptom_reproduction` 只能是 `unknown`；不得在看到分析结果后反向修改复现判据。

多节点的 `collection_state` 非 `complete` 时不得开始本节后续检查，也不得把缺失 Rank 从预期矩阵中删除。重试必须使用新 attempt；
跨 attempt 拼接产物时 `collection_state=incomplete`。

## 2. Dump 后立即检查结构完整性

按 target/golden 或 run A/run B 分别执行以下检查：

1. 记录训练和采集命令返回码、退出方式及日志中的最终落盘提示。确认预期 Step 已执行现场版本要求的
   `PrecisionDebugger.stop()` 和 `step()`；异常退出时，即使存在 `.pt` 文件也不得假定 JSON 已完整写出。
2. 对预期 `Step × Producer` 矩阵逐项检查 `step<N>/rank<R>/dump.json`；已确认的非分布式单进程/单卡运行允许使用
   `step<N>/proc<PID>/dump.json`。文件必须存在、非空且可解析为 JSON。
3. 核对 `task`、`level`、`framework`、`dump_data_dir` 等现场实际字段与本次配置一致；字段在现场版本不存在时记录
   `not-applicable`，不能伪造。
4. 核对 `data` 或现场等价采集列表非空，并检查批准范围内的 Module/API 与必要的 forward、backward、optimizer 边界。
5. 若存在 `dump_error_info.log`，读取并索引。写盘、空间、权限、序列化或数据缺失相关错误使本次采集为 `incomplete`。
6. 记录缺失、额外、重复或冲突的生产者。分布式运行明确预期 `rank<ID>` 时，只有 `proc<PID>` 而缺少该 Rank 仍为
   `incomplete`，`proc<PID>` 不得冒充分布式 Rank。已确认没有分布式 Rank 的单进程/单卡运行，可将 `proc<PID>` 作为合法生产者，
   但必须记录 Node、PID、进程角色及 target/golden 或 run A/run B 身份，并按角色而不是按 PID 数值建立比较对。Rank ID 冲突、
   `proc<PID>` 身份不明或目录覆盖迹象同样为 `incomplete`。
7. `stack.json`、`construct.json` 按本次 `level`、配置和现场版本核对；不要求官方允许为空的内容非空。
8. tensor 模式还须确认 `dump.json` 引用的每个目标数据文件存在、非空、可加载。定向证据记录 SHA-256；大型全量 dump
   仅记录相对路径、大小、mtime 清单，并对最终引用的关键文件计算 SHA-256。

API/Module 数量或 key 集不同可能来自控制流、版本或真实症状。先标为“结构差异待确认”，检查映射、调用次数和采集范围；
不能直接判成采集不完整，也不能在未映射前盲目 compare。

`dump_integrity` 只取以下值：

| 状态 | 定义 | 后续动作 |
| --- | --- | --- |
| `valid` | 预期范围明确，所有必需文件和结构检查通过。 | 继续判定症状是否复现；不能单凭此状态进入分析。 |
| `incomplete` | 已确认缺 Step/Rank/文件、JSON 损坏、引用数据缺失、异常退出或落盘错误。 | 停止分析；经 Primary 批准后补采，无法补采则以证据不足结束。 |
| `unknown` | 预期范围、版本字段、退出状态或关键完整性证据无法确认。 | 停止分析；补齐事实后重新判定。 |

## 3. 独立判定症状可代表性

`symptom_reproduction` 在分析集合上判定，而不是从文件数量或 compare/overflow_check 结果推导：

| 状态 | 定义 |
| --- | --- |
| `reproduced` | 插桩运行在预先声明的等价口径和窗口内仍出现原症状。 |
| `not-reproduced` | 插桩运行已覆盖可比窗口，且预先声明的症状信号明确未出现。 |
| `unknown` | 症状信号缺失、窗口不可比、运行提前终止，或症状迁移但未声明等价规则。 |

三条路径分别按下列对象判断：

- **E01/E02**：状态属于 target/golden 比较对，不要求 golden 单独“出现异常”。只有插桩后的两侧在相同 Step、Rank、样本和项目口径下
  仍不满足训练级 Loss/Global GradNorm 验收标准，才是 `reproduced`；已落回口径内为 `not-reproduced`，无法对齐为 `unknown`。
- **E04**：插桩运行在原 Node/Rank/Step 或预先声明的等价窗口、阶段和边界上，仍由日志、原始报错、显式有限性信号，或已通过
  完整性检查的原始 `dump.json` 非有限统计观察到 NaN/Inf/Overflow，才是 `reproduced`。不得用随后生成或缺失的
  `anomaly_analyze_*.json` 反向证明是否复现。
- **E08**：状态属于受控 run A/run B 比较对。只有插桩后的两次运行在相同随机性契约、Step、Rank、样本和项目口径下仍不一致，
  才是 `reproduced`；已经一致为 `not-reproduced`，无法对齐或控制条件漂移为 `unknown`。

症状的 Step、Rank、阶段或表现发生迁移时，先记录 observer effect。只有迁移仍满足采集前声明的等价判据时才可标为
`reproduced`；否则标为 `unknown`，不得临时扩大定义。

## 4. 联合分析门禁

| `dump_integrity` | `symptom_reproduction` | 是否允许分析 | 处置 |
| --- | --- | --- | --- |
| `valid` | `reproduced` | 允许 | E01/E02、E08 可 compare；E04 可 overflow_check，并继续解释现场产物。 |
| `valid` | `not-reproduced` | 禁止 | 产物仅作为观察者效应或反证索引，不能代表原症状，也不能据此宣布“无异常”或“已修复”。 |
| `valid` | `unknown` | 禁止 | 补齐独立症状信号或取得可比窗口；不能先分析再推断复现。 |
| `incomplete`/`unknown` | 任意值 | 禁止 | 修复完整性或补采；不得通过缩小结论范围绕过门禁。 |

上表默认单节点，或多节点已经满足执行证据完整且 `collection_state=complete`；此前置条件不满足时，无论表内组合为何均禁止分析。

`not-reproduced` 时按以下顺序处理：

1. 保留本次完整 dump，记录插桩、同步、采集范围、性能变化以及症状消失/迁移的观察者效应。
2. 回退本次 instrumentation，并在需要新作业时由 Primary 重新取得批准，以原契约复核 R0。
3. 若 R0 也不再复现，标记复现条件漂移或实验失效，不能把变化归因于 dump。
4. 若 R0 恢复复现，形成“instrumentation 导致跳变”的单变量边界；经批准后逐次尝试更轻量的证据方式，例如缩小
   Step/Rank/scope、由 tensor 降为 statistics，或使用已有日志和最小有限性观测。
5. 若所有可行观测都会抑制症状，或无法获批重采，以 `EVIDENCE_INSUFFICIENT` 结束；不把一次不复现写成修复或根因。

## 5. 分析后完整性

只有通过联合门禁后才执行本节。运行 compare 后记录返回码、成功/失败日志、输出目录和现场 schema，并检查：

- 每个预期 Rank 均有非空、可解析的 `compare_result_rank*.json`，或现场普通 compare 明确声明的 CSV/XLSX 结果；
- 结果中的 Rank、Step、target/golden 身份与输入矩阵一致；
- 输出引用的输入 dump 路径与已通过校验的路径一致；
- `diff_analyze_*.json` 仅按现场 `-da` 语义解释。它缺失本身不能替代返回码、成功日志和逐 Rank 结果校验。

分析产物另记 `analysis_integrity=valid / incomplete / unknown`。任一逐 Rank 结果缺失或损坏时，本次 compare 的
`analysis_integrity=incomplete`，不得据此声明“无差异”或认证根因。

E04 还须记录 `overflow_check` 返回码、成功/失败日志、实际输入目录和现场输出目录。有异常节点时读取
`anomaly_analyze_*.json`；工具明确成功且提示无异常时可能不生成该文件。若独立信号已确认症状复现但工具未发现异常，记录为
工具覆盖范围或语义待确认的反证，不能改写为“原症状未复现”。返回状态或关键输出无法确认时，`analysis_integrity=unknown`。

## 6. Case 记录与 Reviewer 门禁

在 `evidence_index.md` 为每侧 dump 和每次分析分别记录：run/attempt、生产者 Node/Rank/PID、主动作业共享路径或 offline 原始/当前路径与交接证据、`collection_state`、
预期/实际 Step 与 Producer、文件数、总字节数、JSON 解析结果、
错误日志、关键哈希、结构差异以及对应的 `dump_integrity` 或 `analysis_integrity`。在分析集合上另行记录
`symptom_reproduction`、判定口径、独立症状证据、
可比窗口和处理结论。`experiment_matrix.md` 同步记录检查命令、返回码、两种状态和是否阻断后续分析。

Reviewer 必须分别复核 dump 完整性、症状可代表性和分析产物完整性。缺少 `dump_integrity=valid`、
`symptom_reproduction=reproduced` 或 `analysis_integrity=valid` 的对应证据不得进入原症状的根因证据链；尚未执行分析时
`analysis_integrity` 可为 `not-applicable`。被门禁阻断的产物只能支持 observer effect、反证或 `insufficient evidence`。
多节点还必须复核 execution/scheduler 或 handoff 证据、单一 run/attempt、生产者矩阵及 `collection_state=complete`；共享工程
不能替代逐 Node 软件栈证据。
