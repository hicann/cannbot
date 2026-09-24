# TilingKey 编码规则

`GET_TPL_TILING_KEY(v0, v1, ...)` 把调用参数按 `ASCENDC_TPL_ARGS_DECL` 的声明顺序拼成一个位域整数。BOOL 参数直接用值占 1 bit；UINT 参数用值在 DECL 枚举列表中的下标占 `bitWidth` bit。sub-kernel 符号后缀 `_N` 就是这个 tilingKey 值。

## 编码函数

来自 CANN 头文件 `asc/include/tiling/template_argument.h`（`FastEncodeTilingKeyDirect`）：

```cpp
inline uint64_t FastEncodeTilingKeyDirect(
    const TilingDeclareParams& declareParams,
    std::initializer_list<uint64_t> args)
{
    uint8_t totalBits = 0;
    uint64_t tilingKey = 0;
    const size_t minSize = std::min(declareParams.size(), args.size());
    auto argIter = args.begin();
    for (size_t i = 0; i < minSize; ++i, ++argIter) {
        const auto& param = declareParams[i];
        uint64_t encodeVal = *argIter;
        if (param.paramType == ASCENDC_TPL_UINT){
            auto iter = std::find(param.vals.cbegin(), param.vals.cend(), encodeVal);
            if (iter == param.vals.cend()) {
                return INVALID_TILING_KEY;
            }
            encodeVal = iter - param.vals.cbegin();   // 取下标，不是值
        }
        tilingKey |= (encodeVal << totalBits);
        totalBits += param.bitWidth;
    }
    if(totalBits > MAX_BITS_NUM){ return INVALID_TILING_KEY; }
    return tilingKey;
}

#define GET_TPL_TILING_KEY(...) \
    AscendC::FastEncodeTilingKeyDirect(g_tilingDeclareParams, {__VA_ARGS__})
```

相关常量：`ASCENDC_TPL_BOOL=3`、`ASCENDC_TPL_UINT=2`、`ASCENDC_TPL_1_BW=1`、`MAX_BITS_NUM=64`、`INVALID_TILING_KEY=0xFFFFFFFFFFFFFFFF`。

## 计算逻辑

两个输入序列按下标对齐：
- `declareParams[i]`：声明侧，来自 `ASCENDC_TPL_ARGS_DECL`，给出第 i 个参数的 `paramType` 和 `bitWidth`
- `args`：调用侧，来自 `GET_TPL_TILING_KEY(...)`

逐参数处理，维护累加位偏移 `totalBits`（从 0 开始）：

| paramType | encodeVal 取值 | 占位 |
|---|---|---|
| `ASCENDC_TPL_BOOL` | `arg` 原值 | `bitWidth` = 1 bit |
| `ASCENDC_TPL_UINT` | `arg` 在 DECL 枚举列表中的下标；值不在列表 → `INVALID_TILING_KEY` | `bitWidth` bit |
| `ASCENDC_TPL_DTYPE` / `FORMAT` | `arg` 原值 | `bitWidth` bit |

每步：`tilingKey |= (encodeVal << totalBits)`；`totalBits += param.bitWidth`。

声明顺序决定每个参数占哪几位，`bitWidth` 决定段宽，UINT 段额外做"值→下标"映射。总位宽 > 64 → `INVALID_TILING_KEY`。

## 抽象例子

声明 `(BOOL P0, UINT[2bit] P1, BOOL P2)`，P1 的 DECL 枚举列表为 `[7, 3, 5]`，调用 `GET_TPL_TILING_KEY(1, 3, 0)`：

| i | param | arg | encodeVal | totalBits(执行前) | 贡献 |
|---|---|---|---|---|---|
| 0 | P0 BOOL, 1bit | 1 | 1 | 0 | `1 << 0` |
| 1 | P1 UINT, 2bit | 3 | 下标 1 | 1 | `1 << 1` |
| 2 | P2 BOOL, 1bit | 0 | 0 | 3 | `0 << 3` |

→ `tilingKey = 0b0011 = 3`。注意 P1 传值 `3`，编码用的是下标 `1`，不是值 `3`。

## sub-kernel 后缀 _N

asc_opc 编译时，`ASCENDC_TPL_SEL` 的每个 `ASCENDC_TPL_ARGS_SEL` 块实例化一个 sub-kernel，符号名 `<OpType>_<hash>_<N>_mix_aiv` 中的 `N` = 该块参数经上述编码后的 tilingKey 值。runtime 用 host 侧 `SetTilingKey(K)` 选 `…_K_mix_aiv` 符号。

`ASCENDC_TPL_SEL` 内 `ARGS_SEL` 块的展开顺序（块内 `BOOL_SEL(v0, v1)` 按 v0→v1 展开、块间按书写顺序）决定 codegen 实例化遍历顺序，反映在 `.o` 的 `.ubuf` 段排列与弱符号 `V` 表排列上。这个顺序只影响二进制内 sub-kernel 的物理布局，无调度语义——runtime 永远按 tilingKey 值直接选符号。

## 空位

若某个参数组合在 `ASCENDC_TPL_SEL` 中没有对应的 `ARGS_SEL` 块（通常因该组合语义无意义、host 永不设置该 key），则该 tilingKey 值对应的 sub-kernel 不存在，二进制符号表里 `_N` 后缀出现空位。这是设计性的，不是编译失败或死代码消除。多 BOOL 参数时尤其常见——N 个 BOOL 有 `2^N` 种组合，实际有意义的往往少于 `2^N`。

## 常见误解

1. **UINT 参数的 tilingKey = 常量值**。错。UINT 取下标。若 `RANK` 的 DECL 枚举列表为 `[4, 8]`，则 `GET_TPL_TILING_KEY(4)` 编码为下标 0 → tilingKey=0 → `_0`；`GET_TILANGE_TILING_KEY(8)` 编码为下标 1 → tilingKey=1 → `_1`。常量 4/8 不是 tilingKey。
2. **sub-kernel 后缀是连续递增的实例序号**。不一定。后缀是位编码值，多参数时会出现空位（如 3 个 BOOL 参数，若 (0,1,1) 不实例化则 `_3` 缺失，后续组合落在 `_4`、`_5`）。
3. **`ASCENDC_TPL_SEL` 的 ARGS_SEL 顺序 = runtime 调度顺序**。不是。runtime 按 tilingKey 直接选符号，SEL 顺序只决定 codegen 实例化遍历顺序。
4. **源码注释里的 tilingKey 编号一定正确**。不一定。注释作者可能按"连续递增"心智模型手写编号，与位编码实际值不符。二进制符号表的 `_N` 后缀是权威事实。
