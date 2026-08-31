# ADR-125：页面状态与 Profile Agent 助手共享注册语义

## 状态

已接受。

## 背景

左侧导航 tab 可以短暂保留 DOM，但内存回收和刷新必须能重建页面。仅保存 DOM
控件快照无法恢复嵌套 tab、自定义部件、所属 overlay 或表单背后的 JavaScript
模型。服务器 Profile Agent 也需要理解和更新用户正在看的页面，但不能直接
访问浏览器 WebMCP 运行时。

## 决策

1. 每个左侧 tab 拥有版本化的 `FTPageState` 注册表；共享组件以稳定 section
   标识注册可序列化状态；
2. tab checkpoint 写入现有浏览器本地 tab workspace。性能回收销毁 live 注册和
   DOM，但保留序列化状态；路由重建时重新注册并在呈现前恢复；
3. 可复用右侧 Agent drawer 绑定一个 Profile。研究报告使用绑定的 Profile，
   其他助手页面使用当前账户的 `self` Profile；
4. drawer 显示与 Agent 运行时生命周期分离。隐藏 drawer 不停止 Agent；只有打开
   该 Profile 的最后一个 tab 被回收后才停止；
5. 助手页面注册一个版本化 Assistance Document Adapter，负责 schema、导出、
   校验和原子导入。注册会自动挂载轻量右侧触发器和 drawer 壳，页面不重复装配
   这套 UI；Profile 解析、运行时启动、聊天模块延迟到真正打开时；
6. drawer 打开时，浏览器把 schema、完整文档和乐观锁 revision 发布到短期
   Manager 内存通道。FactorTester CLI 对一份完整 JSON 文档执行 inspect、
   validate 或原子 apply；页面 Adapter 完成校验、导入、保存和渲染后才确认成功；
7. 测试助手使用与 `RunSpec.configuration` 相同形状的
   `ResearchConfiguration` 文档；RunSpec 只增加不可变身份和执行元数据，不再
   手写第二份字段映射；
8. 页面文档和应用是按 Profile 隔离的短期认证对象，有版本、大小上限，独立于
   业务端口，不是研究记录，也不写控制库；
9. WebMCP 与 CLI 助手通道保留不同传输，但共享“注册文档、普通校验、不绕过后端
   或 DOM”的原则。

## 后果

刷新和内存回收不再需要保留整个页面 DOM；页面必须为非原生部件显式注册状态。
助手不能写入当前 schema/Adapter 不接受的文档，过期 revision 不能覆盖较新的
用户修改；多个助手 tab 可以共享一个 Profile Agent，不会因某个 drawer 隐藏而
终止另一个 tab 的会话。
