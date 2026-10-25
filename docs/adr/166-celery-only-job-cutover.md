# ADR-166：Celery-only Job 调度收尾计划

## 状态

进行中（2026-10-25）。`plan` 与 `execute` 已由 Celery 承担；旧调度壳仍待物理删除。

## 已切换

- Manager 服务设置 `FACTORTESTER_CELERY_PLANNING=1`、`FACTORTESTER_CELERY_EXECUTION=1`。
- `PlanningDispatcher` 将 submitted Job 发布为 `factortester.jobs.plan`。
- 规划任务持久化 execution plan，并在同一事务中写 execution outbox。
- 执行任务按 `(job_id, attempt)` claim，写 Job/progress/result。
- SSE 从 SQLite 进度读取，不依赖 EventBroker。

## 已删除

1. `scripts/research_job_daemon.py`、旧 `JobDaemon` 调度器；
2. `server/jobs/scheduling/daemon.py`；
3. `LongLivedWorkerPool` 与 `server/jobs/scheduling/worker_pool.py`；
4. artifact sink 已迁移到 `server/jobs/dispatch/artifact_sink.py`；
5. `step continue` IPC 接口已退役。

## 仍需删除

1. `server/jobs/ipc` 的 health/wake/cancel 生命周期兼容层；
2. Manager 的 planning sidecar 子进程（planning 已在 dispatcher）；
3. `server/jobs/scheduling/result_projection.py` 兼容模块；
4. 旧 Job 详情/结果 Web 渲染。

## 约束

- 删除每一层前先运行对应测试并提交。
- 不删除仍在被 Nautilus executor 使用的 artifact sink，直到替换完成。
- 生产部署需同时运行 RabbitMQ、dispatcher、目标端口 worker。
