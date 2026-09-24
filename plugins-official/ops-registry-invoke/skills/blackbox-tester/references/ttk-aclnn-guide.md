# TTK aclnn 模式排障指南（vendor 自定义算子）

本文是将当前工作流部署的 vendor 自定义算子对接 **TTK `aclnn` 模式** 的完整操作手册。
以 `AddCustom`（`aclnnAddCustom`）为贯穿示例，流程对任意本工程算子通用。

环境（`$PY`/`$TTK`/CANN）按 [`../../ttk-env-check/SKILL.md`](../../ttk-env-check/SKILL.md) 的「环境约定」设定，**勿写死路径**。  
TTK 以源码方式使用：`cd $TTK` 后 `python3 -m ttk aclnn ...`。  
命令以 `<OpType>`（驼峰，如 `AddCustom`）/ `<op>`（小写，如 `add_custom`）/ `<aclnnOp>`（如 `aclnnAddCustom`）作通用占位符。

---

## 1. 前置检查

### 1.1 环境变量

| 变量 | 说明 | 如何取得（勿写死） |
|------|------|---------|
| `ASCEND_OPP_PATH` | CANN opp 根目录 | `source <CANN 安装路径>/set_env.sh` 自动导出 |
| `ASCEND_TOOLKIT_HOME` | CANN toolkit 根目录 | 同上 |
| `ASCEND_CUSTOM_OPP_PATH` | **必须为空 / 不设**（见Pitfall 2） | 不设 |
| `$PY` | 执行 python（需 numpy/torch/decorator/ttk） | 环境变量 `PY` 指定，默认 `python3`；见 ttk-env-check |
| `$TTK` | ops-test-kit 检出目录 | 环境变量 `TTK` 指定；见 ttk-env-check |

执行 `source .../set_env.sh` 后再检查 `ASCEND_OPP_PATH` / `ASCEND_TOOLKIT_HOME` 是否已设置。

### 1.2 vendor 部署检查

```bash
OPTYPE=<OpType>   # 如 AddCustom

# 1) load_priority 列表里含 <OpType>
grep load_priority "$ASCEND_OPP_PATH/vendors/config.ini"

# 2) op_api 库已部署
ls "$ASCEND_OPP_PATH/vendors/$OPTYPE/op_api/lib/libcust_opapi.so"

# 3) aclnn 符号存在（驼峰 + GetWorkspaceSize）
nm -D "$ASCEND_OPP_PATH/vendors/$OPTYPE/op_api/lib/libcust_opapi.so" \
    | grep -E "aclnn<OpType>|aclnn<OpType>GetWorkspaceSize"
```

> **头文件位置**：vendor 头文件通常在 `op_api/include/<filename>.h`（注意：**不在** `include/aclnnop/` 子目录，而在 `include/` 根——TTK 已兼容两种路径，无需手动指定）。

### 1.3 Python 依赖

```bash
source docs/{OP}/develop/env.sh    # ttk-env-check 产物，含 PY / TTK / ASCEND_*
: "${PY:=python3}"

# 必须能 import decorator（部分 python env 默认缺失，安装一次即可）
"$PY" -c "import decorator" || "$PY" -m pip install decorator

# 确认 torch / torch_npu / numpy 可用
"$PY" -c "import torch, torch_npu, numpy; print('OK')"
```

TTK 以源码方式执行：需 `cd $TTK` 后 `python3 -m ttk`，`PYTHONPATH` 含 `$TTK`。

### 1.4 kernel_meta 写权限

TTK 启动时默认编译 warmup kernel，产物写入 `$TTK/kernel_meta/`（CWD 须为 `$TTK`，tbe 把 warmup 写到 `./kernel_meta`）。功能测试场景加 `--warmup false` 可跳过 warmup 编译。

```bash
: "${TTK:?}"
ls -ld "$TTK/kernel_meta"   # 检查所有者与权限
# 若不可写（非本用户）：
mv "$TTK/kernel_meta" "$TTK/kernel_meta.bak_$(whoami)"
mkdir -p "$TTK/kernel_meta"
```

---

## 2. 准备用例 CSV（aclnn 模式）

aclnn 模式 CSV 最小必填列（其余列 TTK 补默认值）：

| 列名 | 说明 |
|------|------|
| `testcase_name` | 唯一用例 ID |
| `api_name` | **驼峰** `aclnn<OpType>`（见Pitfall 1） |
| `tensor_view_shapes` | 全部张量位（含输出位）的 shape 元组：`"((8,),(8,),(8,))"` |
| `tensor_dtypes` | 全部张量位 dtype 元组：`"('float16','float16','float16')"` |
| `attributes` | 算子属性 dict，无属性写 `{}` |
| `output_tensor_indexes` | 输出张量位下标（元组字符串）：`"(2,)"` |

`AddCustom` 示例（3 张量位，index 0/1 输入、index 2 输出）：

```csv
testcase_name,api_name,tensor_view_shapes,tensor_dtypes,attributes,output_tensor_indexes
addcustom_f16_01,aclnnAddCustom,"((8,),(8,),(8,))","('float16','float16','float16')",{},"(2,)"
addcustom_f16_02,aclnnAddCustom,"((1,256),(1,256),(1,256))","('float16','float16','float16')",{},"(2,)"
addcustom_f32_01,aclnnAddCustom,"((32,32),(32,32),(32,32))","('float32','float32','float32')",{},"(2,)"
```

> `tensor_view_shapes` 的外层括号包含**全部**张量位（含输出位），与 C 头文件的参数顺序一致。

---

## 3. 准备 TestSpec

使用 TTK 仓官方 TestSpec 示例 `$TTK/ttk/test_spec/examples/` 与 `ttk-how-write-plugin` skill 实例化，或参照以下结构手写：

```python
import torch

__spec__ = {"<aclnnOp>": "<OpType>TestSpec"}   # key 必须驼峰，如 "aclnnAddCustom"

class <OpType>TestSpec:
    def golden(x, y, out=None, **kwargs):   # 输出位须加占位形参（Pitfall 3）
        return [torch.add(x, y)]   # 替换为本算子的 torch 实现

    third_party = {"torch": "torch.add"}
    tolerance = {"float32": {"standard": "stat_rel_err"}}  # 计算类浮点固定使用 stat_rel_err
```

**关键约束**（见Pitfall 2/4）：

- `__spec__` 必须是**模块级赋值**（TTK 用 AST 静态扫描，类名须与映射值一致）。
- key 为驼峰 `<aclnnOp>`（aclnn 模式），value 为 TestSpec 类名。
- golden 方法**返回 `list[torch.Tensor]`**（aclnn 模式要求，与 kernel 模式 numpy 不同）。
- golden 方法按 aclnn C 头文件参数序**位置**接收全部张量位（含输出位）：签名须为每个输出位加 `=None` 占位形参并忽略（带 out 写法见 TTK 仓 `ttk-how-write-plugin` skill 的 `references/aclnn-plugin.md`）。仅**类形式** golden（`__call__`）按名绑定、自动跳过输出位。
- 方法末尾加 `**kwargs` 吸收 TTK 注入的 `full_soc_version` 等 context 参数。

---

## 4. 执行命令

```bash
OPTYPE=<OpType>          # 如 AddCustom
source docs/{OP}/develop/env.sh                    # ttk-env-check 产物
: "${TTK:?}"; : "${PY:=python3}"
CSV=<path/to/blackbox_all.csv>
GOLDEN=<path/to/golden.py>
INPUT_DIST_ARG=$("$PY" <ops-ttk skill 目录>/scripts/derive_input_dist.py --spec <docs/{OP}/spec.yaml 绝对路径>)  # spec data_distribution: normal → --input-dist normal；否则空
OUT=<path/to/result.csv>
VENDOR="$ASCEND_OPP_PATH/vendors/$OPTYPE"
export LD_LIBRARY_PATH="$VENDOR/op_api/lib:$LD_LIBRARY_PATH"
# 关键：不要 export ASCEND_CUSTOM_OPP_PATH（见Pitfall 2）

cd "$TTK"                            # 关键：CWD 必须 == TTK 根（见Pitfall 4）
env PYTHONPATH="$TTK:$(dirname "$GOLDEN"):$ASCEND_TOOLKIT_HOME/python/site-packages" \
    "$PY" -m ttk aclnn -i "$CSV" --pc=1 --task-prof false --run 1 --warmup false $INPUT_DIST_ARG --plugin "$GOLDEN" -o "$OUT"
```

> **与 kernel 模式的差异**：子命令 `aclnn`（不是 `kernel`）；`PYTHONPATH` 无需加 `tbe` impl 目录；`LD_LIBRARY_PATH` 加 `op_api/lib`（共享库加载）；CSV 用 `api_name`（驼峰）+ `tensor_view_shapes` + `output_tensor_indexes`。
> **`--input-dist`**：`uniform`/`normal`（默认 `uniform`），控制输入数据生成分布；spec.yaml 声明 `data_distribution: normal` 的累加类算子必须带 `--input-dist normal`（用 `derive_input_dist.py` 推导，勿手判）。参数权威表见 TTK 仓 `ttk-how-run-test` skill（`$TTK/.claude/skills/ttk-how-run-test/SKILL.md`）。

---

## 5. 合并标准分层 CSV

blackbox-designer 直接交付公共 `ascendc-st-design` 的标准文件：`*_l0_functional.csv`、
`*_l1_functional.csv`、`*_l2_exception.csv`。L0/L1 为正向套件，L2 为负向套件；
`*_oversized.csv` 是当前工作流的资源隔离旁表，不执行。L1 可能比 L0 多非连续字段，必须按列名合并：

```bash
PKG=<operator_package_dir 绝对路径>
SKILL_DIR=<blackbox-tester skill 绝对路径>
OUTDIR="$PKG/tests/blackbox/ttk"; mkdir -p "$OUTDIR"
"$PY" "$SKILL_DIR/merge_cases.py" "$PKG/tests/blackbox/testcases" \
  --positive-out "$OUTDIR/blackbox_all.csv" \
  --negative-out "$OUTDIR/blackbox_l2_neg.csv"
```

---

## 6. 判读 result.csv

执行完毕后 `result.csv` 落盘，含 27 列：

```
testcase_name,network_name,api_name,tensor_view_shapes,tensor_formats,tensor_dtypes,tensor_storage_shapes,tensor_view_offsets,tensor_view_strides,output_tensor_indexes,output_inplace_indexes,attributes,scalar_dtypes,input_data_ranges,precision_tolerances,absolute_precision,scalar_data_ranges,is_enabled,remark,soc_series,priority,dump_file_prefix,manual_tensor_binaries,manual_golden_binaries,precision,precision_status,soc
```

**精度结论判读**：

| 列名 | 精度通过 | 精度失败 | 说明 |
|------|----------|----------|------|
| `precision_status` | `PASS` | `FAIL` | **门禁判据列**（parse_result.py 只需判此列） |
| `precision` | `100.0%`（带百分号） | `GOLDEN_FAILURE` / 低于容差 | 辅助信息，逐元素通过率 |
| `soc` | 设备 SOC（TTK 自动识别，如 `Ascend950...`） | 同 | 设备平台标识 |

终端同步打印 `GOLD: 100.0%` 与 `PRECISION_STATUS: PASS`（每用例一行）。

> **重名用例改名（实测）**：输入 CSV 中存在重名 `testcase_name` 时，TTK 自动把后出现的改名为
> `<原名>_<api_name>_dup<N>`（`testcase_manager._rename_duplicate_case_name`，WARNING 日志提示），
> result.csv 里是改后名。按用例名回查原始分层 CSV 时须先归并该后缀
> （`parse_result.py --by-layer` 已内置：最长已知前缀 + `_..._dupN` 后缀匹配）。

---

## 7. Pitfall 速查表

| 现象 | 根因 | 处理 |
|------|------|------|
| `fail_reason=SOC_NOT_SUPPORT`（Pitfall 1） | CSV `api_name` 未驼峰，或拼写错误 | 改为驼峰 `aclnn<OpType>`，如 `aclnnAddCustom` |
| `No module named impl.dynamic` / golden 加载异常（Pitfall 2） | 设了 `ASCEND_CUSTOM_OPP_PATH` | 取消该变量；走 vendor 源（靠 `config.ini` `load_priority`） |
| `GOLDEN_FAILURE` / golden 返回类型不符 / `TypeError: takes N positional arguments but N+1 were given`（Pitfall 3） | TestSpec golden 方法返回单个 Tensor 而非 list；或 golden 未接收输出张量位 | golden 须返回 `list[torch.Tensor]`，如 `return [torch.add(x, y)]`；为每个输出位加 `=None` 占位形参并忽略；参考 TTK 仓 `$TTK/ttk/test_spec/examples/` |
| `PermissionError: ./kernel_meta/warmup.json`（Pitfall 4） | `$TTK/kernel_meta` 属他人，当前用户不可写 | 重建可写目录（见 §1.4）；或加 `--warmup false` 跳过 warmup 编译；且必须 `cd $TTK` 再运行 |
| `No module named 'tbe'` / `No module named 'decorator'`（Pitfall 1 延伸） | `PYTHONPATH` 缺 `$ASCEND_TOOLKIT_HOME/python/site-packages`；或 env 缺 `decorator` | 补加 `python/site-packages` 到 `PYTHONPATH`；`pip install decorator` 一次 |
| `Scanned 0 custom spec functions` / spec 未加载 | `__spec__` 未模块级赋值，或 key/value 与类名不一致 | `__spec__ = {"<aclnnOp>": "<ClassName>"}` 模块级赋值，类名与 value 一致 |
| `got an unexpected keyword argument 'full_soc_version'` | golden 方法签名无 `**kwargs` | 方法末尾加 `**kwargs` |
| aclnn 头文件找不到（Pitfall 5） | 头文件在 `op_api/include/` 根而非 `include/aclnnop/` | TTK 已自动回退，无需手动指定；确认 `config.ini` `load_priority` 含 `<OpType>` 即可 |
| `PARAM_COUNT_MISMATCH`（Pitfall 6，E2E 实证） | CSV `attributes` 键名 ≠ 部署 aclnn 参数名（OpDef 属性名与 aclnn 参数名可不同，**可选属性 codegen 常加 `Optional` 后缀**，如 OpDef `axes`→aclnn `axesOptional`）；或可选属性未在用例显式给值（TTK 把可选属性也计入必需参数槽） | 属性键改用 aclnn 头文件 `aclnn<Op>GetWorkspaceSize` 里的**参数名**；每个接口参数（含可选）都在用例显式给值 |
| golden `truth value of an array is ambiguous` / `only 0-dimensional arrays...`（Pitfall 7） | TTK 把 CSV 属性以 **numpy array** 传给 golden，golden 里 `if attr:` 或 `int(attr[0])` 崩 | golden 勿对数组做布尔判断；用 `np.asarray(attr).ravel()` + `int(arr[0]) if arr.size else 默认` 取标量 |
| **段错误 / `exit code -11 (SIGSEGV)`，且崩溃只发生在值依赖输入非空的用例（Pitfall 8）** | 值依赖输入（OpDef `.ValueDepend(OPTIONAL)`）被当 tensor 传、走了 **`aclnnXxxTensor`** 双接口变体；TilingFunc 在 host `GetData()` 解引用 device 指针（值依赖输入为空时不读值故不崩） | 改走 **IntArray 基接口** `aclnnXxx`，把该输入放进 `attributes`（`aclIntArray`）、**不占 tensor 位**；生成侧在 `01_parameter_description.md` 标明 `aclIntArray`，并映射进 `02_test_factors.yaml`。`preflight.py` 已加双接口 / tensor 数守卫，会在上设备前拦截 |
| **正向用例全 `NO_OUTPUT`（AIV 崩溃）或 `errcode95`（MTE DDR 越界），而同 kernel/同数据的 C++ `tests/aclnn` ST 全过（Pitfall 9，E2E 实证）** | TTK aclnn 模式用 `rtSetDevice` 直接初始化、不经 `aclInit` 且不自动扫 vendor 目录，`liboptiling.so` 从未被加载 → `TilingFunc` 从未注册/调用，kernel 收到垃圾 `TilingData`（如 `ubFormer=1`、`stds=[0,0,0,0]`、`tilingKey` 随机）→ MTE 越界 | 判定证据先对（kernel `Printf` TilingData 字段损坏 / host `TilingFunc` 未被调用 / C++ ST 全过）→ `env.sh` 设 `LD_PRELOAD` 预加载 vendor `liboptiling.so` + 启动脚本调用 `TbeLoadSoAndSaveToRegistry` 注册（见 `ttk_preload/sitecustomize.py` 可复刻）后**重跑**；属框架加载问题，非 kernel/tiling 缺陷，勿进修复循环 |
| `PARAM_COUNT_MISMATCH` 冒烟即全量拦截（Pitfall 6 引申） | 含可选属性的接口，用例未对可选属性显式给值（TTK 计入必需参数槽） | **生成侧规避**：`02_test_factors.yaml` 里每个接口参数（含可选 attr）都显式建模并提供合法值域，导出用例逐条带显式取值；命中后按 Pitfall 6 核对属性键名 |
| **正向用例几乎全 `errno 561002 tiling fail`（仅空 tensor N=0 短路 PASS），且 C++ `tests/aclnn` ST 直调 vendor TilingFunc 全过、最小 Python 脚本直调 aclnn API 也过（Pitfall 10，E2E 实证）** | CANN `NnopbaseLoadTilingSo` 以 **`RTLD_LOCAL`** dlopen vendor tiling `.so`，vendor `OpImplRegisterV2`（TilingFunc 注册器）的注册仅对自身 namespace 可见，对 `libnnopbase.so` 不可见 → `NnopbaseExecutorDoTiling` 找不到 TilingFunc → -1 → 561002。此现象只在 TTK e2e（触发 GE init）出现 | 先按「黑盒失败分诊 SOP」分诊（最小复现 + `nm -D` 排除 built-in 冲突）→ 用 `references/sitecustomize_rtld_global.py.templ` 生成 `sitecustomize.py` **RTLD_GLOBAL 预加载** vendor tiling `.so`，并确保随包/启动自动生效（如装到 CANN site-packages）后重跑；属 CANN 框架加载问题，非 kernel/tiling 缺陷，勿进修复循环 |

## 8. 黑盒失败分诊 SOP（防多轮误诊）

全量黑盒大规模失败（如 561002 / NO_OUTPUT / errcode95）时，**先分诊、后修复**，禁止直接进入对 kernel/tiling 的修复循环。诊断顺序固定：

```bash
# ① 最小复现（≤1 次）：a. C++ ST（直调 vendor，不经 TTK e2e）全过 ⇒ 算子概率无错
#                        b. 最小 Python 直调 aclnn API（不经 TTK Opc() 初始化）过 ⇒ 指向 TTK/GE 初始化路径
# ② nm 排除 built-in 冲突：
nm -D "$ASCEND_TOOLKIT_HOME/opp/built-in/op_impl/ai_core/tbe/op_tiling/lib/linux/x86_64/liboptiling.so" 2>/dev/null | grep -i "<OpType>"
#    无命中 ⇒ built-in 无该算子 TilingFunc，排除"built-in 抢注"假设
# ③ C++ ST 过 + 最小 Python 过 + nm 无命中，仍 561002 ⇒ Pitfall 9/10（框架加载），用对应模板修复，勿改 kernel/tiling
```

判据：①② 任一步命中算子侧（C++ ST 失败、或 nm 命中 built-in 且冲突成立）才进 kernel/tiling 修复；
否则一律先按框架/平台加载问题处理（Pitfall 9/10 模板）。bounding_box_decode 561002 曾 8 轮误诊——当时把
`MergeTypesToImpl` 日志误读为 built-in 冲突，一条 `nm -D` 本可在首轮排除。
