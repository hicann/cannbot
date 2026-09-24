# st-verifier · 参考脚本

`st-verifier` 子agent 用这里的脚本对 ST 测试产物做实质检查。

## coverage_audit.py — 结构覆盖度审计

```bash
python3 skills/st-verifier/references/coverage_audit.py \
    <输出目录>/design_doc_cases.json <design_facts.json> <opspec.json>
```

独立用白盒统一入口的 `build_model(dims)` 重算该阶段【期望】的结构覆盖签名集，与交付 cases 的【实际】覆盖比对：
size/align/dtype 结构轴须全覆盖；广播分支（design_facts 设 `allow_broadcast_pairs`）须有真实广播对。
报告打印到 stdout；**退出码 0 = 覆盖达标，1 = 不足**（供 st-verifier 卡口）。

- **只信 build_model 重算的期望，不读 cases/JSON 里 agent 自述的 target_sigs** —— 独立于被测产物。
- 逻辑单一真源在 `skills/ascendc-whitebox-design/references/whitebox_designer.py`（`build_model` / `_dims_from_opspec` /
  `case_sig` / `_coverage_audit_cases`）；本脚本只薄封装、不复制逻辑，避免漂移。

## 其它检查（非脚本化，见 SKILL.md）

用例符合设计（`docs/{OP}/design/BranchRoute.md` / `docs/{OP}/design/Validation.md`「端到端测试用例矩阵」测试点全命中）、用例是否全部纳入框架（条数一致）、框架正确性、执行结果 —— 由 st-verifier
据 SKILL.md 的检查清单逐项核对。
