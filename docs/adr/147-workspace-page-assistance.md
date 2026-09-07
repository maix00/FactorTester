# ADR 147 — 按工作区 Tab 定位页面填写

日期：2026-09-07。关联：#380；补充 ADR 125、126。

## 决策

保留现有页面 adapter 的 schema/export/validate/import 和 assistance draft/apply/acknowledge 协议。独立 Tab 注册 adapter；嵌套对象 overlay 不覆盖独立 Tab 的注册。工作区提供打开的研究文件夹、独立 Tab、父子关系与当前 Tab ID。未声明 adapter 的页面只提供导航元数据。

打开助手时发布工作区的页面合同，接收端复用一个 long-poll，按 application.tab_id 分发。CLI inspect 与 drafts create 支持 --tab-id；草稿绑定创建时的目标，切页不再隐式重定向。

服务端按账号及 Profile 隔离。self 可见整个工作区；其他 Profile 仅可见其仍是成员的研究范围。发布和读取/写入时复核研究成员关系。关闭目标 Tab 会清除对应上下文和队列；上下文沿用现有 TTL。

页面合同随既有 Tab durable 状态保存，缓存回收不保留额外 DOM。后台修改暂存于目标 Tab durable 状态，服务端回执保持 queued；激活时先确认权限和有效期，再由目标 adapter 校验、导入、重绘并 acknowledge。校验或版本冲突不得报成 applied。页面刷新使用同一持久化恢复路径。查看/运行配置与最终提交仍由原页面处理。

回测/IC 的可填写草稿必须至少含一个策略组/配置组，schema 与 adapter 校验共同约束。报告页声明为只读页面文档，提供当前身份和现有 CLI --help 入口；正文仍走报告 authoring CLI。可见报告每 5 秒检查现有 index，变化后重绘并保留阅读位置，后台页面暂停读取，回收时清理定时器。浏览器登录会话只控制页面上下文开放，服务器 Agent 继续使用 Profile capability，不增加浏览器登录依赖。

## 验证及边界

覆盖 self/研究范围隔离、明确目标、关闭、版本冲突、后台持久化、冷缓存恢复、CLI 兼容性和共享 header 的浏览器渲染。打开的浏览器工作区是上下文来源，不扫描磁盘或枚举未打开页面。后台接收成功不等于已应用，Agent 必须等待应用回执。

回退：回退本次代码；保留用户原页面数据。新增 assistanceSnapshot/pendingAssistance 是浏览器会话状态，不迁移服务端用户配置库。
