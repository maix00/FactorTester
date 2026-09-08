# Xpert 会话修复验收（2026-09-09）

上游固定为 20d26e03db7ca740cac78e5c69a95eb18dbdb613，差异由 scripts/xpert-chatkit/host-integration.patch 管理。

- Steer 复用原生 pending 队列和 follow_up_consumed 事件。请求确认不代表应用；等待期间显示“等待应用”，实际用户项事件触发 consumed。明确失败恢复队列，不自动重复发送。
- Commentary 是正文；reasoning 只展示服务商公开的 summary。终端 dynamicToolCall 的 arguments/contentItems 与普通 commandExecution 都进入同一历史投影；详细输出保持按轮次懒加载。
- 附件字节保存在 Profile 工作区 uploads/UTC日期/随机ID/原文件名。同名上传互不覆盖。会话 ID 是引用关系，不作为发送前上传必须存在的文件目录。
- 附件引用以紧凑结构后缀进入 Provider 的权威用户消息，历史投影恢复卡片，前端隐藏结构后缀。没有新增第二份会话正文存储或数据库迁移。引用包含路径、大小、类型和 SHA256。
- 自己预览复用工作区 7997 下载授权；上级预览先验证原有会话可见权限，再确认该路径确实出现在指定会话中，按文件大小和 SHA256 签发下载授权。不会开放上级对整个工作区的浏览。
- 旧版 uploads 根目录文件不移动、不删除；没有历史内容校验值的旧消息不能伪造为冻结附件。
- 原生附件标签接入相同的 Radix Dialog 预览，图片/PDF 懒加载，其余格式下载；关闭或卸载释放 Blob URL。
- 思考模式沿用服务商声明的 reasoning_effort。仅支持 none 的模型提供关闭项；不声明能力时禁用，不伪造服务商开关。

验证：聚焦 Python/JS 52 项；原生组件15项；Chrome/WebKit 初始历史、懒加载、附件选择/拖放、历史附件预览、IME、窄屏代码块通过。浏览器这部分使用隔离会话适配器；线上附件与发布版本另行验证。旧消息无法恢复从未保存的内容，不据此删除历史。
