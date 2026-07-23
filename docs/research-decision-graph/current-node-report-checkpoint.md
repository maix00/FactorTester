# Current-node incremental report checkpoint

Research Agent 在当前节点完成一项语义核验后即可登记报告项，不必等待
Graph `advance`。正文仍由本地、内容寻址的 journal artifact 保存；服务器仅保存
可审计的报告项哈希、coverage 与 artifact ref。

对报告项 \(i\)，标准身份为

\[
h_i=\operatorname{SHA256}\!\left(
\operatorname{canonical}\{
r_i,s_i,k_i,c_i
\}\right),
\]

其中 \(r_i\) 是报告要求，\(s_i\) 是 subject ref，\(k_i\) 是内容类型，
\(c_i\) 是包含中文叙事、LaTeX、列表或表格的本地正文。服务器登记的 fragment
只包含 \((r_i,s_i,k_i,h_i)\)，因此 Agent context 的长度与审计存储预算解耦。

使用流程：

1. `cycle entry-validate` 生成包含 `report_submission` 的 projection。
2. 本地 publisher 把完整正文写入不可变 journal artifact。
3. 执行
   `factortester research-graph checkpoint-report INSTANCE BRANCH
   --node-id NODE --projection-file projection.json
   --journal-artifact-ref journal-artifact:sha256:...`。
4. 后续 transition 只需引用回执的 `checkpoint_ref`、`item_hashes` 与
   `coverage`；不再携带正文。

同一回执重复提交是幂等的；同一节点的不同批次会追加保存。服务端在单个事务
中确认节点仍为 current node，校验失败或节点已改变时不会写入回执，也不会更新
branch 或插入 transition trace。
