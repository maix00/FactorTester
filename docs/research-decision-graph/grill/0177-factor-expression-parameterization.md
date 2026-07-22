# Grill 177 — Factor-expression parameterization obligations

Status: closed; decisions 177.1–177.10 accepted and consolidated into Grill 179.

This is a document-grounded audit of how a factor-expression inspection may
produce a new Verification Obligation without turning every data column into a
hard-coded checklist item. It is not runtime Agent context.

## Current scenario

`SgCCS` fixes adjusted close as the centre-price input of a rolling high/low
range. Source inspection showed that the input can be represented by a
`FactorParam`, producing the independent candidate family `SgCCSParam`.
The default `P=CA` candidate has deterministic expression-tree equivalence to
the original family, but numerical pointwise equivalence and research validity
remain unproven.

## 177.1 — Opportunity fact versus obligation proposal

**Question.** Should every fixed data column in a factor expression
automatically create a Verification Obligation, or should deterministic
inspection expose only a parameterization opportunity and let a Research Agent
propose an obligation when the alternative is economically coherent and could
change the research decision?

**Recommendation.** Separate the two. Deterministic inspection reports the
expression location and structural context. The Research Agent applies factor
semantics and first-principles reasoning. It proposes one obligation only when
the alternative could change factor construction, TrialPlan design, permitted
use, or the bounded decision. An independent reviewer remains required when
the semantic uncertainty is material.

**User response.** Accepted.

**Final resolution.** A deterministic `Factor Column Reference Summary` is an
expression-inspection fact, not cognitive debt and not a Verification
Obligation. Fixed columns do not create obligations mechanically. The
Research Agent may identify a parameterization opportunity and convert it into
an obligation only after stating the economically coherent alternative, its
decision impact, and an observable discharge path. Irrelevant constants,
identifiers, and arbitrary Cartesian substitutions are rejected. Coupled
inputs such as a high/low range must be considered as a coherent definition
rather than independent column swaps when their semantics require it.

`SgCCSParam` is a candidate implementation produced in response to the
question. Its existence neither proves that the obligation was necessary nor
discharges it. Default structural equivalence is implementation evidence only;
it is not numerical equivalence or alpha evidence.

**Acceptance evidence.**

- source inspection can report a bounded parameterization opportunity without
  mutating Research Cycle state;
- no obligation is created merely because an AST contains a fixed column;
- an accepted proposal identifies the coherent alternative, affected decision,
  scope, and discharge criterion;
- coupled price inputs are not silently expanded into an unconstrained
  Cartesian parameter grid;
- `SgCCS` and `SgCCSParam` retain independent factor-family lineage;
- default-expression equivalence cannot be reported as factor validity.

## 177.2 — Compact deterministic expression fact

**Question.** Should the factor-semantics backend expose a compact index of
parameterization opportunities, or require the Research Agent to reload source
or a complete AST whenever it considers this question?

**Recommendation.** Emit a bounded, source-free expression fact derived by
deterministic inspection. Do not include a recommended replacement, economic
role, obligation status, or allowed parameter domain.

**User response.** Accepted, with the requirement that the Agent also be told
which CLI command can retrieve the information.

**Final resolution.** The normal Agent packet does not contain source or a full
AST. The deterministic backend exposes only compact expression facts. The
Research Agent uses a compact CLI read path, then applies economic semantics
before proposing any obligation. The exact projection was simplified further
in 177.3.

Current code evidence shows that `/custom-factors/api/validate` already builds
the FactorExpr tree and can serialize a full visual graph, while
`factortester custom_factors describe` returns a tree representation and can
optionally return source or the full debug graph. The opportunity projection
should therefore reuse the existing validated expression rather than parse
source a second time, but it needs a compact CLI projection so Agents do not
load the existing heavy outputs.

**Acceptance evidence.**

- column-reference discovery reuses the validated FactorExpr and performs no
  additional database read or source parse;
- routine Agent context contains neither source, full tree text, nor visual
  graph;
- the backend summary contains no recommended replacement or economic-semantic
  conclusion;
- the selected detail can be retrieved by a provider-neutral CLI command;
- unchanged factor revision and request identity produce a stable result with
  no write;
- cross-owner source policy is preserved: executable visibility does not grant
  source or mathematical-expression access.

## 177.3 — Reuse `describe`; output `ColumnRef` values

**Initial proposal.** Add a dedicated
`custom_factors parameterization-opportunities` command with opportunity IDs,
revision arguments, coupling groups, and lazy detail references.

**User response.** Rejected as unnecessarily complex. The validated
FactorExpr already contains the referenced price columns as `ColumnRef`
objects; find them and return them with the existing description.

**Final resolution.** Do not create an opportunity object, opportunity
registry, detail endpoint, dedicated command, or new persistence owner. Walk
the already validated FactorExpr, retain the distinct `ColumnRef` values in
first-appearance order, and add `column_refs` to the existing compact
`factortester custom_factors describe <factor-ref> --json` output. Existing
parameter metadata already shows which inputs are `FactorParam`. Comparing the
two facts is sufficient input for Agent semantic reasoning.

The command continues to omit source unless `--source-code` is explicitly
requested and omits the full visual graph unless `--debug-graph` is explicitly
requested. Existing source-access policy applies unchanged. The Research Agent
is told to run this existing command when factor-expression semantics are under
inspection.

**Acceptance evidence.**

- `SgCCS` reports `column_refs` containing `CA`, `HA`, and `LA`;
- `SgCCSParam` reports fixed `HA` and `LA` ColumnRefs while its existing
  parameter metadata reports `P` as a `FactorParam` with default `CA`;
- extraction preserves first appearance, removes duplicates, and does not
  confuse `ParamRef` with `ColumnRef`;
- no additional source parse, database read, endpoint, command, or persisted
  object is introduced;
- default JSON still omits source and the full debug graph;
- the Harness tells the Agent to use the existing `describe --json` command
  only when factor-expression semantics are relevant.

## 177.4 — Existing obligation-discovery Skill owns semantic review

**Question.** Should reviewing `column_refs` for economically coherent
parameterization become a separate capability/Skill, or a factor-expression
lens inside the existing `research-obligation.discover` capability?

**Recommendation.** Keep it inside the existing obligation-discovery Skill.
The factor-semantics node already conditionally invokes that capability when
semantic inspection exposes a material question. A separate capability would
duplicate the same source, Claim, obligation, and review boundary.

**User response.** Accepted, with clarification that the Agent must see the
factor's original expression at this step, check it for economic errors, and
consider whether its `ColumnRef` inputs should become `FactorParam`, as in the
`SgCCS` to `SgCCSParam` candidate change.

**Final resolution.** Do not add a capability, Skill, graph node, or universal
parameterization checklist. During source-accessible factor-semantics review,
the Research Agent examines the original `factor_expr()` and its deterministic
column/parameter summary. It checks economic mechanism, unit and price-basis
consistency, direction, timing, numerator/denominator construction, and other
factor-specific errors. It then asks whether a fixed ColumnRef has an
economically coherent parameterized alternative that could change the bounded
decision. Only a material, falsifiable question with an observable discharge
path becomes a Verification Obligation.

A semantics-changing implementation such as `SgCCSParam` retains independent
factor-family/version lineage. Its default equivalence with `SgCCS` is tested
separately; creating the family does not discharge economic or empirical
obligations.

**Acceptance evidence.**

- the existing obligation-discovery reference explicitly instructs the Agent
  to inspect the original expression and `column_refs` at factor semantics;
- the inspection lenses include economic meaning, units, price basis,
  direction, timing, construction, and coherent parameterization;
- no obligation is generated when the alternative is immaterial, incoherent,
  or merely technically expressible;
- a semantics-changing candidate receives independent lineage and trial-ledger
  identity;
- SgCCS/SgCCSParam is covered as an end-to-end acceptance scenario without
  treating default structural equivalence as alpha evidence.

## 177.5 — Original-expression loading and source authority

**Question.** How should the Agent see the original expression without putting
private source into the routine 6000-byte packet, Graph trace, or report?

**Recommendation.** Prefer direct local reading from the claimed Profile
worktree. When no local file is available but source access is authorized, use
the existing `factortester custom_factors describe <factor-ref> --source-code
--json` command. Keep source local and load it only during factor-semantics
inspection. If cross-owner policy permits execution but not source or
mathematical-expression access, preserve an explicit visibility limitation and
do not claim an economic-expression review.

**User response.** Accepted.

**Final resolution.** The Agent must genuinely inspect the source-accessible
original `factor_expr()` at factor semantics, but no server packet duplicates
the source. Local source is preferred; the existing authorized CLI is the
fallback. The Graph persists factor/configuration/version hashes and bounded
semantic decisions, not source. Reports may explain the reviewed semantics but
do not reproduce private expressions. Lack of source authority cannot be
silently replaced by a guessed formula.

**Acceptance evidence.**

- a Profile Agent reads the exact worktree revision bound to its research;
- an authorized CLI fallback returns source only with the explicit existing
  `--source-code` flag;
- ordinary next/resume packets and report projections contain no factor
  source;
- server trace retains revision/evidence refs rather than source text;
- cross-owner execution-only access cannot retrieve source, expression tree,
  or `column_refs` that would reveal the mathematical expression;
- a visibility limitation remains auditable and prevents a false claim that
  source-level economic review was completed.

## Reused decision — Factor identity after correction or enhancement

Decision 160 already governs the identity disposition and is not reopened. A
bug repair preserving the declared economic meaning creates an immutable child
version in the same family. A compatible enhancement may remain a same-family
version. A change to prediction target, mechanism, input domain, trading role,
output interpretation, or a candidate that remains independently meaningful
creates a derived family with explicit lineage. `SgCCSParam` therefore remains
an independent family derived from `SgCCS`; neither source path nor evidence is
overwritten.

## Open branch for 177.6

The current graph can discover a material question at `factor_semantics`, but
its only successful outgoing path enters `validation_design`. Determine how an
economic-expression defect or a material parameterization candidate routes to
factor correction/derivation without forcing an invalid TrialPlan or stopping
an unaffected original hypothesis.
## Grill 177.6 — 回测前语义发现必须有恢复路径

**决定：接受。** `factor_semantics` 增加到既有
`factor_improvement_required` 的恢复边，不增加新节点或新持久化对象。

- 当前因子存在经济语义或表达式错误时，只移动受影响的当前分支；旧版本和证据保留。
- 独立且仍有意义的增强方向使用既有 branch fork；原分支继续，派生分支进入改进流程并记录 `derived_from`。
- 路由必须来自已接受的 `revise_factor` adjudication，不能接受 Agent 自报布尔值。
- 该路径发生在 TrialPlan 冻结前，因此不得要求已有 TrialPlan stage。

## Grill 177.7 — 工作包候选范围与分支执行范围分离

**决定：接受，并由 177.8 进一步收窄迁移语义。** 获批且已形成
revision manifest 的派生家族自动进入同一 Work Package 的候选范围；
Work Package 范围由分支已经绑定的语义投影形成，不增加 scope 表。
每个 Hypothesis Branch 只冻结解除其当前义务所需的目标和比较项，
不得把工作包内全部候选机械装入 TrialPlan。跨家族比较使用各自独立的
单因子 RunSpec，不得误称为多因子组合；候选集合同时进入 multiplicity
语义。工作区可包含多个家族，但分支执行必须绑定准确 revision manifest，
不得用工作区“最新配置”替代分支身份。

## Grill 177.8 — 严格推广家族的研究焦点迁移

**决定：接受，并收窄 177.6 的默认 fork。** 当派生家族严格包含原因子
作为特例时，默认在同一 Work Package 内开始新的 hypothesis lineage，
把主研究焦点迁移到派生家族；仅当两个家族仍需独立研究时才 fork。

派生裁决必须产生可执行的迁移义务：用相同数据、时序、成本和产品范围，
以两个独立的单因子 RunSpec 验证特例参数下的结构与数值等价、证据可迁移
范围及限制。这是跨家族配对比较，不是多因子组合。旧证据只可映射到已验证
的特例参数点，不得外推到其余参数。迁移义务解除后，原因子不再机械进入
后续 TrialPlan；等价性失败则重新打开实现或语义义务，且旧证据不被删除。

## Grill 177.9 — 晚发现语义义务的有限恢复

**决定：接受。** 当前位于 `validation_design` 且尚未提交 job 的 MaxA
分支可经已接受的 `revise_factor` adjudication，沿新增的
`validation_design__factor_improvement` 恢复边进入既有改进流程；不得伪造
TrialPlan 或重建 Work Package。已经运行的 job 不强制终止，而是在
`result_audit` 使用既有恢复路径，并给结果附加已知语义限制。不受影响的
branch/job 继续。图不增加 `any_node` 万能恢复边；只在确有阶段语义的节点
声明有限恢复路径。

## Grill 177.10 — 既有 job 证据按特例参数迁移

**决定：接受。** 原 job、RunSpec、EvidenceEnvelope、统计表和 trace 身份
保持不变，不复制、不删除。等价性验证通过后，Research Cycle 以 Claim
scope delta 引用原 job evidence、等价性 evidence 和迁移裁决，声明其适用
于派生家族的精确特例参数及相同时序配置。等价性待验证时，旧证据仍可见但
不得声称已经迁移；失败时它仍是有效的原因子证据。

迁移同时继承全部样本暴露、trial ledger 与 multiplicity 历史。旧样本不得
重新命名为新家族 holdout；只有探索新的参数点才增加新的试验次数。报告只
增加范围说明和按需审计链接，不产生证据副本。
