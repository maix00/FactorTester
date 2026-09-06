# Issue 373 — 对象写入、同步与草稿生命周期审计（进行中）

基线：origin/feat `173da7337`；独立 worktree `fix/issue-373-object-write-sync`。
本文件记录进行中的证据，不是部署验收回执。

## 已复现和定位

- 单因子新建/编辑向家族 configuration PUT 发送单元素 params_list，替换整个列表。
- 2026-09-06 只读查询：MaxJJW 的 default:CA 最新 authored 参数为 10m/Rev=1；
  issue 372 发布前备份中为 1m/Rev=0。应保留两个不同身份，不能只恢复旧参数覆盖新参数。
- 本机 7998 Manager 来自 main 发布目录，7999 写服务 /proc/PID/cwd 却是旧 feat 根目录。
  固定端口发现逻辑优先取了 feat 的约定端口；隔离测试已复现。
- 本机 outbox 有测试 provider `custom:CA@header-icon-check`，错误为
  `factor source provider identity is inconsistent`。一次实体拒绝使整个批次提前返回。
- 列表 refresh 参数只调度异步同步，随即读取旧镜像；没有等待或完成状态。
- 产品分类/产品组 legacy reconcile 无条件重新 upsert 旧 authored 数据，可覆盖 peer 编辑/删除。
- 策略库使用独立 SQLite CRUD，尚未注册 account-domain 类型或 7997 源码适配器。
- 临时下拉框保存回调引用了其作用域之外的 items/render；删除没有传播新的选中值。
- overlay 继承父页面 pageState，多个因子 create 注册使用相同 key；当场家族数组没有保存。
- 下拉框混用普通流、CSS anchor、fixed portal；需要统一 viewport 定位及 top-layer 生命周期。

## 已开始的修复，尚未发布

单行追加/按冻结 ref 编辑、镜像优先读取、写时复用冻结结果、共享强制刷新 barrier、
写后调度、backfill 防止复活、分页完成判定、无效 outbox 条目不阻塞其余条目、
固定服务 checkout、下拉框新建入口及编辑/删除状态、overlay 草稿隔离、定位回归。

## 尚须完成的验收矩阵

- 因子、家族、集合、产品组、产品分类、策略：新建、编辑、删除；两端交替写；
  刷新后 ref 集合一致；冷启动、离线、冲突、历史版本、源码按需读取。
- 策略：复用 account-domain 元数据与 7997 字节适配器，不把源码塞进元数据；
  接收端可读、可编辑，历史 revision 保留。
- 单因子存储：测量每家族参数数量增长时的计算次数、SQLite 写量和 outbox 大小；
  决定是否将注册按独立身份规范化，保持冻结身份与迁移映射。
- 临时对象：统一下拉框 CRUD；tab/overlay 隔离；刷新恢复；关闭后按引用释放；
  所有测试配置页扫描旧独立新建入口。
- 浏览器：滚动/缩放/裁剪容器/模态框的下拉定位、header 图标样式、新建与编辑背景。
- 所有测试类型：配置生成、实际小规模运行，最近失败任务复现及修复。
  本机近期历史错误包括 IC 缺 start_date/end_date、缺产品组、scheduler_restarted、worker_crashed；
  必须检查其部署版本和当前复现，不将历史错误直接当作当前根因。
- 服务器智能体辅助填写：权限、对象候选、配置应用、运行配置生成的真实闭环。
- 各服务器部署验收：必须核对 7998、7999、7997 实际源码内容，不能仅验证 Manager SHA。
- 用户已授权创建/修改/删除验收对象；验收通过后可清理无用迁移脚本和备份，
  仍需先查发布入口引用和回退用途，保留正在用于 CA 恢复的备份。

## 当前验证

最近一次综合聚焦回归：226 项通过，含 147 项前端模块检查；另有 8 条已有 pandas
时间单位弃用警告。下拉框 Node 合成测试不代表浏览器验收。旧客户端测试已改为
临时数据库隔离，并修正 metadata 测试桩的 username 关键字契约。
故障注入验证配置/镜像/outbox 同事务回滚；100 行同家族中编辑一行只冻结一行，
保留其他行的原始冻结版本。策略并发版本、旧表迁移、权限与字节 hash 校验有隔离回归。
最新临时对象快照修改仍待后续回归。
尚未完成全量聚焦回归、真实浏览器闭环、部署、数据恢复和清理。
