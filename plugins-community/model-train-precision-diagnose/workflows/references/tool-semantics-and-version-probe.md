# 精度诊断工具的现场确认与结果解释

更新日期：2026-09-18。官方 master 文档只作为当前参考；现场安装版本和实际输出是执行真源。

## 使用前确认 msProbe 的实际版本与接口

### 名称映射与未安装门禁

msProbe 的名称不能互换使用：

- 工具名、CLI 名和 Python import 名：`msprobe`；
- pip distribution 名：`mindstudio-probe`；
- wheel 文件名通常使用下划线形式 `mindstudio_probe*.whl`。

先在已确认的实际训练 Python 环境中执行只读探测；`python -m pip` 必须与训练进程的 `sys.executable` 对应：

```bash
python -m pip show mindstudio-probe
command -v msprobe
msprobe --help
```

若 distribution、CLI 或 import 任一缺失，记录 `msprobe_status=not-installed/partial/unknown`、解释器、原始错误和已检查的安装源，
不得尝试 `pip install msprobe`，也不得从 import 名、CLI 名或仓库名猜 distribution。只有诊断确实需要 msProbe，才查阅与现场
CANN、torch/torch_npu、Python、OS/架构匹配的官方
[msProbe 安装指南](https://gitcode.com/Ascend/msprobe/blob/master/docs/zh/msprobe_install_guide.md)，确定版本和安装形态，并由 Primary
向用户确认后修改环境。官方 PyTorch 快速入门中的在线安装基名是：

```bash
python -m pip install mindstudio-probe
```

是否需要 `--pre`、固定版本、额外模块或源码编译必须以匹配现场版本的官方指南为准。默认索引找不到包不能改装 `msprobe`；应记录
索引错误，再由用户提供或批准可用的内网源、官方/可信 wheel（`mindstudio_probe*.whl`）或官方源码构建方案。安装后重新执行
`pip show`、CLI、import 和签名探测；不得只凭 pip 返回成功认定工具可用。

### 已安装环境的版本与接口

记录 CLI、Python 包、distribution 和签名：

```bash
command -v msprobe
realpath "$(command -v msprobe)"
msprobe --help
msprobe compare --help
msprobe overflow_check --help
python - <<'PY'
import importlib.metadata
import inspect
from pathlib import Path
import msprobe
from msprobe.pytorch import PrecisionDebugger, seed_all

print("msprobe_module=", Path(inspect.getfile(msprobe)).resolve())
for dist in importlib.metadata.packages_distributions().get("msprobe", []):
    print("distribution=", dist, "version=", importlib.metadata.version(dist))
print("seed_all", inspect.signature(seed_all))
print("PrecisionDebugger", inspect.signature(PrecisionDebugger))
for name in ("start", "stop", "step", "register_custom_api", "restore_custom_api"):
    fn = getattr(PrecisionDebugger, name, None)
    print(name, inspect.signature(fn) if fn else "unavailable")
PY
```

命令或导入失败时记录原始错误，返回上节的未安装/部分安装门禁，不根据网上配置继续猜测。

## 解释 `msprobe overflow_check` 的结果与边界

当前官方规则：

- 输入必须指到 PyTorch dump 的 Step 层级；
- 有异常节点时主分析产物为 `anomaly_analyze_{timestamp}.json`；
- 明确报告 `Cannot find any anomaly node...` 时可能不生成分析文件；
- 没有文件只覆盖本次成功解析的 dump，不证明未采集范围无异常。

`compare_result*` 和 `diff_analyze*` 不是 overflow_check 产物。

过滤行为也必须以现场安装版本为准：从 `inspect.getfile(msprobe)` 对应包目录定位实际 `ignore_rules.yaml`，记录绝对路径、
内容摘要和采用的规则。当前官方说明列举了未初始化内存相关节点（`empty`、`empty_like`、`empty_strided`、`fill`）、
分布式通信数据覆盖前的野值，以及 `masked_fill_` inplace 输入；现场文件缺失、存在多份或内容不一致时写 `unknown`，不得假定已过滤。
内置规则命中不等于根因判断完成，仍需按症状 Skill 检查实际写入者、生产者和消费者。

参考：[First Network Overflow/Underflow Node Analysis](https://gitcode.com/Ascend/msprobe/blob/master/docs/en/user_guide/overflow_check/overflow_check_instruct.md)

## 解释 `msprobe compare` 的结果与边界

当前 PyTorch `compare -da` 首差异分析会输出 `compare_result_rank{rank_id}_{timestamp}.json` 和
`diff_analyze_{timestamp}.json`；普通比对可能输出 CSV/XLSX。以现场帮助、成功日志和实际输出目录为准。

statistics 普通比对的相对误差字段为 `MaxRelativeErr`、`MinRelativeErr`、`MeanRelativeErr`、
`NormRelativeErr`。常规路径直接消费工具生成的 `Result`/`Err_message`，不在 Agent 中重复实现判定器；其中 `error`/`warning`
可能由 NormRelativeErr、非有限值、dtype、shape、requires_grad 或非 Tensor 标量等不同原因触发，必须按 `Err_message` 分类。
只有 `Result`/`Err_message` 缺失、冲突或版本不明时，才确认单元格单位并按现场规则复核。当前文档的 NormRelativeErr error
语义是输入/参数 `< 10%` 且输出 `> 50%`；放大 warning 表述为 10 倍，当前本地源码使用严格 `> 10`，并在输入误差为零时
以输出 `> 10%` 单独判断。阈值、边界和特殊 API 排除项以现场安装版本为准。

`compare -da` 的逐 Rank JSON 不保证包含普通比对的 `Result`。当前本地源码主要使用 `is_same`、`op_items` 和安装包内
`diff_analyze_threshold.yaml` 的阈值生成首差异；必须从实际导入的 msProbe 包目录定位该文件，记录绝对路径、SHA-256、
指标列表和阈值。当前源码中的四类相对误差阈值均为 `0.5`（50%），但不得把该值硬编码到流程，也不得用它替代项目的
Loss/Global GradNorm 验收门槛。

普通 compare 的 `Result`、`-da` 的 `is_same` 和 `diff_analyze_*.json` 都只用于节点级定位，不代表训练级 mismatch 是否达标。
执行分析前后还必须遵循 [Dump 完整性、症状可代表性与分析门禁](dump-integrity-and-compare-gate.md)。

参考：[PyTorch Precision Comparison](https://gitcode.com/Ascend/msprobe/blob/master/docs/zh/user_guide/accuracy_compare/pytorch_accuracy_compare_instruct.md)

### 使用 `merge_result` 汇总多 Rank 结果（仅 E01/E02 可选）

`merge_result` 是普通多卡 compare 完成后的结果整理工具：从逐 Rank 的 compare XLSX 中提取配置指定的 API/Module 和指标，
把同一名称的各 Rank 值横向汇总，并按指标写入 `multi_ranks_compare_merge_{timestamp}.xlsx` 的不同 sheet。它不读取 dump
重新比对，也不替代 `compare -da` 的首差异分析。

只有 E01/E02 已出现通信节点或 rank-local 可疑证据时，才按有限值偏差 Skill 的结果分析分支使用；不得把它扩展为 E04、E08、
Reviewer 或通用工作流的必经步骤。执行前运行 `msprobe merge_result --help` 并记录现场差异。
当前官方文档和本地源码的约束为：

- 只读取普通 compare 的 XLSX；需要汇总时应在 compare 阶段使用 `--xlsx`，CSV 和 `compare -da` JSON 不能作为输入；
- 不支持 MD5 比对结果；输入应全部为 tensor 真实数据结果或全部为 statistics 结果，不能混用模式；
- `api` 必填，`compare_index` 必须是对应 dump 模式支持的指标子集；未指定指标时按现场版本提取该模式支持的全部指标；
- 输出中的空白表示对应 Rank 找不到该 API/Module，不表示该 Rank 通过；`N/A`、`unsupported`、`Nan` 按现场输出解释；
- 汇总表是派生的跨 Rank 观察视图。离群 Rank 或通信节点只能成为继续核查的候选，不能替代逐 Rank 原始结果、训练级门槛、
  collective 参与者/调用序号核对或修复验证。

## 明确 `summary_mode: "md5"` 实际记录的内容

当前 PyTorch 动态图中该模式记录 CRC-32 校验值及统计信息，字段名 `md5` 不代表密码学 MD5。`bench_path`、
`diff_nums`、`is_enhanced` 等字段先确认现场版本。

参考：[PyTorch Data Dump](https://gitcode.com/Ascend/msprobe/blob/master/docs/zh/user_guide/dump/pytorch_data_dump_instruct.md)

## 明确 `detect_anomaly` 能检查什么

PyTorch 官方只保证：启用上下文的前向会让失败反向打印相应前向 traceback；`check_nan=True` 会在反向生成 NaN 时抛错。
它不是通用前向/反向 NaN/Inf 检查器。前向、反向 Inf 和 Optimizer/Scaler 边界使用显式 `torch.isfinite` 或 dump。

若出现 `NotImplementedError: Operator aten._is_any_true.default does not have a sharding strategy registered`，表示当前 PyTorch/DTensor 组合中的 detect_anomaly(check_nan=True) 检查路径缺少相应的分片策略，并非已检测到模型 backward 异常。按现场 PyTorch
版本核对，经授权后可在隔离环境按 [PyTorch PR #170951](https://github.com/pytorch/pytorch/pull/170951) 中的临时规避方法继续验证；否则进入 dump 流程。记录原始报错、版本和处理方式。

参考：[torch.autograd.detect_anomaly](https://docs.pytorch.org/docs/2.14/autograd.html#torch.autograd.detect_anomaly)

## msProbe 训练 dump：确认实际入口与 Debugger 接入位置

本节只用于解决 **msProbe 插桩应写在哪里**，不负责通过调用栈定位精度根因。目标是确认：

- 哪个运行时进程、worker 和 Rank 实际执行目标 forward、backward 或 optimizer 阶段；
- 哪个稳定生命周期对象适合创建并持有 `PrecisionDebugger`；
- `start()`、`stop()` 和 `step()` 分别应放在哪些执行边界，才能覆盖批准的 Step 和计算阶段。

训练启动脚本可能只负责拉起任务，launcher/driver 也可能不执行模型计算。若把 msProbe 接到这些位置，可能出现未生成 dump、
只采到部分 Rank、生命周期边界错误或多进程写入冲突。因此应优先复用官方框架示例，再用最小运行时证据确认示例与现场一致。

### 优先参考官方框架示例

先查阅官方[常见框架 dump 工具使能](https://gitcode.com/Ascend/msprobe/blob/master/docs/zh/best_practices/dump_enable_guide.md)。该指南的多数框架示例只在图片中标出源码入口和 Debugger 边界。
下表依据官方文档转录，纯文本 Agent 使用它作为图片的文本化导航，不以“无法读取图片”跳过官方示例。若指南修订已变化，先核对更新内容再沿用：

| 指南示例 | 图片所示候选源码位置 | 图片所示候选边界 |
| --- | --- | --- |
| MindSpeed-LLM | `mindspeed_llm/training.py` 的训练循环 | 在 `train_step(...)` 前创建并 `start(model=model)`，调用后 `stop()`、`step()` |
| MindSpeed-MM | `mindspeed_mm/training.py` 的训练循环 | 在 `train_step(...)` 前创建并 `start(model=model)`，调用后 `stop()`、`step()` |
| LLaMA-Factory | 实际加载的 `transformers/trainer.py`，`Trainer._inner_training_loop` | 在单次更新中的 `training_step(...)` 前开始，在该次更新结束后停止并推进 step |
| accelerate + DeepSpeed | 指南示例工程的 `accelerate/examples/nlp_example.py`，`training_function` | 在 dataloader/`accelerator.accumulate(model)` 的单次更新内、模型 forward 前开始，在 optimizer/scheduler/zero-grad 边界后停止并推进 step |
| torchtitan（FSDP2） | `torchtitan/train.py`，`Trainer.train` | 在 `self.train_step(inputs, labels)` 前 `start(self.model_parts)`，调用后 `stop()`、`step()` |
| VERL（FSDP） | `verl/workers/fsdp_workers.py`，`ActorRolloutRefWorker.generate_sequences` | 用实际 rollout 模型开始，包围 `self.rollout.generate_sequences(...)`，随后停止并推进 step |
| VERL（FSDP） | 同文件与类的 `update_actor` | 用实际 actor module 开始，包围 `self.actor.update_policy(...)`，随后停止并推进 step |
| VERL（FSDP） | 同文件与类的 `compute_log_prob` | 用实际 actor module 开始，包围 `self.actor.compute_log_prob(...)`，随后停止并推进 step |
| VERL（FSDP） | 同文件与类的 `compute_ref_log_prob` | 用实际 ref policy 开始，包围 `self.ref_policy.compute_log_prob(...)`，随后停止并推进 step |
| VERL（SGLang） | `sglang/srt/model_executor/model_runner.py`，`ModelRunner` | 在 `__init__` 创建 Debugger；`forward` 开始处 `start`，结束处 `stop()`、`step()` |

该表只把指南图片中的**源码路径、符号和相对计算边界**转成文字，不复制截图行号、`dump_path`、task/level、Rank 或示例对象表达式。
其中 LLaMA-Factory 图片实际落在安装环境的 Transformers 源码，accelerate 图片落在示例工程；VERL（FSDP）指南也明确提示不同配置或
使能方式可能变化。VERL（SGLang）正文示例还限定了组件版本和 eager 模式。指南中“使能确定性的位置”图片不替代 E08 对随机性设置
有效状态的现场检查，也不能仅凭标题推导具体确定性 API。

若现场框架、后端和任务路径落在表中范围，先把对应行作为候选接入方案，不先打印调用栈；若表中没有对应任务路径或现场符号已经变化，
候选位置记为 `unknown`，再进入后续调用路径探测。

复用示例前仍须核对：

- 现场框架、后端、训练/rollout/推理路径和执行模式与示例适用范围一致；
- 示例中的文件、类或方法在运行时实际加载路径中存在，语义仍覆盖目标 forward、backward 或 optimizer 阶段；
- `PrecisionDebugger`、`start()`、`stop()`、`step()` 的现场签名与示例用法兼容；
- 多进程、多 Rank 场景下，接入代码运行在目标计算 worker，而不是只运行在 launcher/driver。

核对通过后，按“设置 PrecisionDebugger 与 start/stop/step 的生命周期”中的最小批准窗口验证实际命中情况。只有官方示例不覆盖现场
框架/后端/任务路径、示例适用条件与现场版本或配置不一致，或者最小验证没有命中目标计算进程、Rank 或阶段时，才进入后续调用路径探测。

### 核对官方示例与现场加载路径

插桩前记录框架、后端、版本、启动器、进程/worker 角色和 Rank 映射。导入运行时模块并执行
`inspect.getsourcefile(module)`；只有输出路径对应的文件才是候选修改对象。若包、软链、容器挂载或 Ray worker 指向其他位置，
先修正目标和权限。记录模块路径、启动命令、修改 diff 和回退方式。

框架名称或源码目录不能单独证明实际计算路径。官方示例是首选接入依据，但不能脱离其框架、后端、任务路径和执行模式适用范围，
也不能在现场文件或符号已经变化时机械照搬源码行号。运行时加载路径和最小命中验证用于确认示例在当前环境确实生效。

### 静态检查仍无法确定接入位置时：临时探测调用路径

调用路径探测只用于回答“目标计算由哪个进程中的哪个训练对象执行”，从而选择 msProbe 接入位置；探针输出本身不是精度证据。

1. 先明确本次要采集的阶段是 forward、backward、optimizer 中的哪一段，以及目标 Step 和 Rank。只有这些边界明确后，才能判断
   某条调用路径是否与本次采集相关。
2. 选择一个已由日志、运行时源码或既有证据确认会在目标阶段执行的代表 API。不要默认所有模型都经过
   `torch.nn.functional.linear`，也不要用未验证的 API 命中情况推断训练入口。
3. 由 Primary 在执行前向用户确认探针对象、Rank、Step、持续窗口和回退方式后，使用最小范围的临时调用栈探针。探针可放在框架允许的 hook，或临时包装该代表 API；仅记录
   进程、worker 身份、Rank、加载文件和必要调用栈，不借此改动训练逻辑或采集 Tensor。
4. 用探针结果确认实际计算位于 launcher/driver、训练 worker、Ray actor、pipeline stage 还是其他子进程，并沿栈找到：
   - 持有模型或训练器的稳定对象；
   - 包含目标 forward/backward/optimizer 的训练 Step 方法；
   - 该方法在目标 worker/Rank 上的实际加载文件。
5. 将上述结果转成候选接入方案：在哪个计算进程创建 `PrecisionDebugger`、由哪个对象持有，以及 `start/stop/step` 应包住哪段
   生命周期。接入方案尚未按下一节验证前，不得开始正式 dump。
6. 探针使用后恢复原 API/hook，保存修改和回退证据。若 compile、dispatch、图捕获、通信时序或症状发生变化，记录观察者效应。

调用栈只证明代表 API 已命中的一条实际路径。未命中的 Rank、分支、backward 或 optimizer 路径仍为 `unknown`，需要分别确认；
不能因为某条 forward 路径已命中，就推定整个训练生命周期的接入位置已经正确。

### 设置 PrecisionDebugger 与 start/stop/step 的生命周期

- `seed_all` 如需使用，应位于相关随机状态、模型和数据组件初始化之前；参数和覆盖范围按现场签名确认。
- `PrecisionDebugger` 应在实际计算进程中由稳定生命周期对象持有，通常每个目标 worker/Rank 初始化一次；不要在每次 forward
  临时重复创建，也不要只在不执行模型计算的 driver 中创建。
- `start()` 放在批准的采集区域之前，`stop()` 放在该区域全部目标计算之后。只采前向、采前向+反向、或覆盖 optimizer 时，
  边界不同，不能机械复制某个框架示例。
- `step()` 必须在 `stop()` 后；需要反向数据时还必须位于 backward 完成之后。具体参数、`model` 和 `rank_id` 均按现场签名与
  真实 Rank 映射确定，不能照搬 `rank_id=self.gpu_id` 等示例。
- 多进程、多 Rank 和 Ray 场景逐个确认目标 worker 已命中，dump 路径不会因 Rank ID 重复或多进程写同一路径而覆盖。

插桩后先用最小批准窗口验证：每个目标 Rank 的初始化、`start/stop/step` 均实际执行，日志和 dump 目录与预期 Step 对应；随后执行
[Dump 完整性、症状可代表性与分析门禁](dump-integrity-and-compare-gate.md)。未命中目标计算路径时，不得通过扩大 dump 掩盖接入点错误。

VERL SGLang 指南中的 `ModelRunner`、eager、图捕获和 Ray 环境配置属于特定版本的 rollout/推理接入示例，不是本 Plugin 的默认
训练插桩方案；当前任务落入推理路径时按范围边界标记 unsupported，不直接套用。

## 核对候选 CANN 算子的实际实现与官方契约

该分支只在症状定位已收敛到具体 API/Module，且需要核对非 Tensor 参数、shape、mask、重载方向或算子契约时使用；不得在
Preflight 或全网未知阶段扫描整个 CANN 安装目录。

### 1. 确认候选算子、符号和实际安装路径

1. 从已验证的运行栈、日志或实际加载源码确认前端 API、调用方向/重载和候选底层 CANN 符号。仅凭相似名称不得建立映射。
2. 优先从进程实际加载的动态库路径反推组件根；再核对现场已设置且路径有效的 `ASCEND_HOME_PATH`、`ASCEND_OPP_PATH` 等变量。
   不假定单一安装布局，也不从文件系统根目录做无界搜索。
3. 只在已验证根目录内按精确符号和必要的规范化名称查找安装包文档、头文件、Python/C++ 实现或算子元数据。
4. 记录绝对路径、CANN/组件版本、SHA-256、符号、签名或约束摘录，以及这些证据对应的分析侧身份（target/golden、run A/run B
   或 E04 单次运行）、Node 和容器环境。

环境变量只提供候选根，不证明当前进程从该路径加载。路径不存在、存在多个版本或无法映射到底层符号时，将对应事实写为
`unknown`，不得挑选最符合假设的一份源码。

### 2. 现场证据不足时查询官方资料

现场资料不足且运行环境提供只读 WebFetch 时，从[昇腾文档](https://www.hiascend.com/document)或候选算子所属的 CANN 官方社区
GitCode 仓库查询与现场版本匹配的算子/API 契约、实现或元数据；记录直接 URL、产品/组件版本或 revision、查询日期和适用约束。不得用搜索摘要、第三方博客或其他版本示例补造 API、参数或边界行为。
官方页面无法访问、由脚本渲染而无法取得正文、或找不到匹配现场版本时，回退到现场安装资料、用户提供的 URL/快照，或将证据写为
`unknown`。

### 3. 区分实现证据、契约证据和修改权限

- 现场安装源码描述本次运行可能采用的实现，版本匹配的官方文档描述预期契约；两者不能互相替代。
- 实现与文档冲突时，记录为版本/契约不匹配假设，保留双方证据，并通过单变量实验验证；不得静默选择其中一方为真。
- 只读证据不能单独认证数值根因。仍须满足对应症状的首差异/首异常、修复和回退门禁。
- 本流程不授权修改 CANN 安装包、算子源码或系统文件；需要修改时必须建立独立实验并由 Primary 确认具体范围。
