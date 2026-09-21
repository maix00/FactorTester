# Agent 研究矩阵跑批

研究结果以服务器上的 Run、RunSpec 和 Job 为准。本地台账仅记录矩阵单元到 Job 的指针，不能把临时 JSON 文件或终端输出当作研究证据。

跑批前从**目标服务器当前因子目录**导出快照。快照须包含 `server_id`、带时区的 `generated_at`，以及每个因子的 `owner_ref`、`alias`、`ref`；十分钟后重新导出。为每个独立市场或实验批次创建不同的 `batch_id`，并把计划和台账放在仓库及系统临时目录之外。计划中的每行有唯一 `key`、`owner_ref`、`factor_alias`、`factor_ref`：

```json
{
  "batch_id": "T-20260921",
  "server_id": "public-main",
  "rows": [{
    "key": "T/DFP/20d",
    "owner_ref": "principal:alice",
    "factor_alias": "Signal|N:20d",
    "factor_ref": "factor:v2:...",
    "run_spec_hash": "sha256:..."
  }]
}
```

```bash
python scripts/research/batch_ledger.py init \
  --manifest plan.json --catalog current-catalog.json \
  --ledger-dir "$HOME/ResearchRuns/factor-matrix"
```

`init` 检查 ref 是否仍与当前别名一致、矩阵键是否重复，以及目录是否持久。相同 `batch_id` 只能恢复原计划；计划变化必须用新 `batch_id`。每行的 `run_spec_hash` 应由 CLI 的 Run 预览取得，用它确认冻结配置与因子引用；提交后立即把返回的权威标识记入台账：

```bash
python scripts/research/batch_ledger.py record \
  --ledger "$HOME/ResearchRuns/factor-matrix/T-20260921.json" \
  --catalog current-catalog.json --key T/DFP/20d \
  --run-id RUN_ID --job-id JOB_ID --run-spec-hash SHA256_HASH
```

`record` 会再次检查目录快照；重新登记因子后，旧 ref 会被拒绝。同一矩阵键只能重复写入完全相同的 Job 绑定。恢复时先读台账并逐一向服务器查询 Job 状态和结果；不要重置结果文件，也不要因为本地记录缺失就断言服务器 Job 未运行。新结果应使用新的批次或明确的新矩阵键。

测试时直接运行 `python -m pytest ...` 并检查退出码，或使用仓库 `scripts/test.sh`。确需把输出送入 `tail` 时先启用 `set -o pipefail`；否则管道可能把失败显示为成功。生产负载与数据修复仍遵循仓库授权门槛。
