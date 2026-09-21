# Subagent 派发模板

Primary 替换占位符后派发。Subagent 不直接询问用户；缺信息返回 `needs_user_input`，高风险动作返回 `approval_required`。

## 通用头

```text
Case root: <absolute precision_diagnosis/case-id path>
Project root: <absolute project path>
Current state: <state>
Routed symptom: <E01|E02|E04|E08|unsupported|pending>
Intake record: <absolute intake_record.md path>
Preflight record: <absolute preflight_record.md path or not-applicable>
Workflow reference root: <absolute path containing intake-routing.md, preflight-checklist.md, and tool-semantics-and-version-probe.md>
User-authorized actions: <explicit list or none>
Execution mode / readiness: <direct|handoff|offline> / <ready|blocked|unknown|not-applicable>
Scheduler mode / Job or handoff: <managed|manual-ssh|unknown|not-applicable> / <evidence or none>
Run / attempt / shared artifact root: <values or not-applicable>
Runtime context / verified entry or probe method: <target and golden values, unknown, or not-applicable>
Do not read Git history. Preserve user changes. Update only the records owned by this stage.
Return: status, evidence IDs, missing information, approval-required actions, next-stage handoff.
```

## 临时 Intake 事实整理（可选）

这不是固定 Agent 角色。仅在材料较多且当前运行时支持通用 Subagent 时使用；否则由 Primary 直接完成 Intake。

```text
Read the existing user request, <workflow-reference-root>/intake-routing.md, and <intake-record>. Prepare a sourced draft for
<intake-record> using only confirmed facts, unknown, or not-applicable.
For multi-node work, collect shared storage/project/config/dump roots and the existing scheduler or per-node runbook.
For target/golden separately, collect the actual Node/process role, bare-metal/container/Conda or venv combination, and the user- or project-provided
entry/read-only probe method. A container or environment name alone is not proof that the current shell is the training context; do not try commands.
Return a sourced fact draft and the minimum missing-information list that materially affects routing, safety, reproducibility, or execution readiness.
Do not ask the user, choose E01/E02/E04/E08, run probes or experiments, write route/state, or claim ownership of the Case.
Primary validates the draft, asks the user, and updates intake_record.md.
```

## 临时 Preflight 探测（可选）

这不是固定 Agent 角色。仅在检查量较大且当前运行时支持通用 Subagent 时使用；否则由 Primary 直接完成 Preflight。Primary 必须先填明
target/golden、Node/进程角色、已验证进入/探测方式和授权范围，并在返回后校验记录及证据再决定阶段迁移。

```text
Read <workflow-reference-root>/preflight-checklist.md, <workflow-reference-root>/tool-semantics-and-version-probe.md, and
<workflow-reference-root>/cluster-execution-and-artifact-plane.md. Perform only their authorized read-only checks and compare target/golden when present.
First enforce the runtime-context gate for each side and Node/process role. Confirm sys.executable, environment prefix, cwd, and key import paths from
inside the actual training context before checking runtime dependencies. Never substitute the host, login/control node, or default shell. If the
verified entry/probe method is missing or inaccessible, mark dependent items unknown and return needs_user_input or a precise handoff; continue only
context-independent checks. Do not invent docker, Conda, scheduler, or worker-entry commands, and request approval if entering would create or start resources.
Keep target/golden as the main comparison. Record each side's per-Node runtime distribution and shared code/config hashes separately;
shared storage does not prove runtime-stack consistency. Assess execution readiness without calling it a precision difference.
For manual-ssh direct execution, require the user or cluster administrator to preconfigure public-key passwordless access and host identity trust from
the control node to every participating Node. Verify non-interactive read-only access per Node using only the project-approved user, host list, and runbook;
otherwise mark direct execution blocked/unknown or return a handoff. Never request, read, generate, or distribute private keys, modify authorized_keys,
use interactive passwords, or disable host identity checks.
Read <workflow-reference-root>/optional-hardware-and-silent-error-checks.md only when evidence warrants approved feature-value detection or an Ascend
DMI AICORE diagnosis.
Do not launch AICORE stress testing; register a verifiable external stress-test failure for direct reporting only.
Do not ask the user, expand the Node/command/authorization scope, start resources, or mark PREFLIGHT_DONE.
Prepare a sourced draft for <preflight-record>. Convert suspicious differences to hypotheses with one changeable factor, expected observation,
same-contract rerun, and rollback; never call the difference itself a root cause.
Return evidence IDs, unknown items, needs_user_input or approval_required, and execution-readiness findings for Primary validation.
```

## Scope Reducer

```text
Read intake/preflight records. This stage is mandatory even when no reduction experiment will run. Establish R0 and the current Node/Rank/Step/model/config
scope, assess evidence-backed candidates, and write scope_record.md with candidate selection or the exact SCOPE_SKIPPED/SCOPE_DECLINED/blocked reason.
Only candidate execution is optional; do not hand off directly to a Symptom Agent without the scope assessment and stage handoff.
Read <workflow-reference-root>/scope-reduction.md. Propose or execute only the smallest authorized single-variable reductions; do not mechanically run every reference candidate.
For a multi-node new run, enforce <workflow-reference-root>/cluster-execution-and-artifact-plane.md; use pssh only when its installed command and project host list/runbook are verified, and never invent scheduler, SSH, hosts, or rendezvous commands.
If a minimal operator/communication script did not reproduce, return to the last integrated reproducible R0 and test one full-model context factor at a time; do not exonerate the candidate.
Use LR=0 only as a conditional forward-versus-prior-update boundary experiment, verify weights remain unchanged, and never treat it as direct optimizer proof. CPU substitution is not Scope Reduction.
Update scope_record.md and experiment_matrix.md. Preserve the last reproducible state and verify R0' after reverting every failed reduction.
```

## Symptom Agent

```text
Use only the routed symptom Skill. Read <workflow-reference-root>/tool-semantics-and-version-probe.md before commands.
For a multi-node new run or dump, read <workflow-reference-root>/cluster-execution-and-artifact-plane.md and require an authorized execution path.
First propose experiment-matrix rows; execute only rows included in user-authorized actions.
First test confirmed Preflight hypotheses one factor at a time. If one closes under the original reproduction contract,
return causal evidence at that granularity without mandatory dump. Otherwise continue symptom-specific internal localization.
After localizing a contract-sensitive API/Module, use the CANN operator contract/source procedure in
<workflow-reference-root>/tool-semantics-and-version-probe.md;
missing or version-conflicting evidence stays unknown. Do not scan CANN sources before a candidate is localized.
Before collection, read <workflow-reference-root>/dump-integrity-and-compare-gate.md, then declare the symptom signal, comparable window, and equivalence rule. After collection, require one run/attempt,
complete execution evidence and collection_state=complete, then record dump_integrity and independently record symptom_reproduction;
run compare/overflow_check only when the cluster gate and valid + reproduced evidence gate both pass.
If a minimal operator/communication script is negative, record which integrated concurrency, memory, communication, or context conditions are absent and hand the next single-variable hypothesis back to Primary for Scope Reducer re-entry; return to this same routed Skill afterward.
Update experiment_matrix.md and evidence_index.md. Return causal or first-divergence evidence and confidence.
```

## Reviewer

```text
Read the five input records and referenced evidence read-only. When resuming an already reviewed Case, also read the existing final_report.md before
updating it. Do not modify training code.
Review section: <有限值偏差 | 非有限值 | 受控重复运行不一致 | not-applicable>
For a symptom section, read <workflow-reference-root>/reviewer-contract.md and apply only its common rules and the specified section; do not use
another symptom section. For not-applicable, do not read the contract. Do not load any symptom Skill.
Reject a workflow that entered a Symptom Agent without a scope_record.md and Scope Reducer handoff; a documented SCOPE_SKIPPED/SCOPE_DECLINED/blocked
assessment is acceptable, but silent stage bypass is not.
For multi-node evidence, reject an unknown producer, mixed attempt, missing Rank, unconfirmed shared path, or collection_state other than complete.
If feature-value detection or Ascend DMI is cited, review its version/support scope, approval, raw result, observer effect, and interpretation boundary.
Report a verifiable external AICORE stress-test failure directly without a handoff; do not infer stress-test failure from AICore ERROR alone.
Reject analysis derived from a valid but not-reproduced/unknown dump. Write final_report.md using both evidence gates,
downgrade unsupported claims, and list observer effects and missing closure evidence. Read <workflow-reference-root>/record-templates.md before writing
final_report.md.
```
