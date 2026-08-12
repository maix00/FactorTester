# Capability Detour 与 Entry Resolution 的状态边界

状态：已确认
适用范围：Factor Research Graph 分支状态、回放、continuation 与报告投影

## 决定

`capability_detour` 是单层的协调状态。一个研究分支在任意时刻最多只有
一个活动 episode 和一个恢复目标。`capability_gap`、
`capability_resolution`、Skill 审查和代码修复之间的往返沿用同一 episode，
不得压入新的 capability frame。

`entry_resolution` 是另一套独立状态。目标节点的 entry gate 可以把研究导向
前置节点，而前置节点本身又可能被 entry gate 阻塞，因此它使用有序的 LIFO
frame 栈。内层完成后先恢复外层，最终重新检查最初目标节点。

两套状态可以同时存在，但不得合并：

- capability 修复可以暂时打断一个尚未完成的 entry 流程
- capability 恢复后继续既有 entry 栈
- entry frame 不创建 capability episode
- capability episode 不进入 entry frame 数组

## 持久化与回放不变量

Capability Detour：

- 每个 `(instance_id, branch_id)` 最多一条活动记录
- 状态不得包含 `frames`、`parent_episode_ref` 或 depth
- 再次进入 capability 协调节点只能 `retain` 当前 episode
- 只有显式恢复边可以清除 episode，并且目标必须等于原恢复目标
- 报告中只能有一个绑定该 episode 的 capability 特殊小节

Entry Resolution：

- canonical 状态保存 `frames: [outer ... top]`
- 只有目标节点自身存在未决 entry requirement 时才 push
- 返回时必须验证当前 Graph、checkpoint、义务和 requirement 的 guard hash
- guard 输入变化时不得复用旧 frame，必须重新计算
- `push`、`route`、`wait`、`resume`、`resolve`、`abandon` 均产生服务端事件
- 事件作为普通报告条目写入服务端声明的当前报告容器，不创建新的章节或特殊小节

历史报告与时间线：

- 报告正文是独立的 authoring document，不从 Graph 重新生成
- 时间线只提供导航和报告容器定位；读取失败不得阻断报告正文
- 新 trace 只按自身冻结的 `capability_detour_delta` 回放，不使用后续 Graph
  重新校验历史推进
- 没有 delta 的旧 trace 只按既成路径回放；旧 episode 离开原节点以外的节点时
  标为 `legacy_exited`，不得伪称满足当前恢复合同
- Graph 升级不得改写旧 trace、旧报告正文或旧报告绑定

## 变更门禁

后续实现、代码审查或上下文恢复不得根据摘要重新解释上述边界。任何改变都必须：

1. 明确指出与本文件冲突的条款
2. 获得新的用户决定
3. 同时修改状态合同、回放和报告投影
4. 先更新不变量测试，再修改生产实现

最低回归必须同时证明：

- 连续 capability gap/resolution 往返仍是同一个 episode
- capability 状态拒绝嵌套 frame 或父 episode
- 两层 entry diversion 按 LIFO 顺序恢复
- entry guard 输入变化会使旧恢复帧失效
- capability 特殊小节保持单一，entry 事件不会生成第二个特殊小节
- 修改或升级 Graph 后，旧时间线仍可读取，报告正文即使时间线失败也可打开
