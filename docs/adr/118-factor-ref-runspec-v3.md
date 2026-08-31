# ADR 118：因子引用与语义 RunSpec v3 顺序

## 状态

已接受，针对 Issue #287。

## 背景

测试 authoring 曾把一个因子重复表示为 `factorAlias`、`factorAliases`、analysis 级 family alias 和共享 family catalog。Alias 只是显示标签，可能变化或冲突，不能作为运行时身份。规范 RunSpec 还会把对象键排序序列化，使面向人的字段顺序变成字母顺序，而不是后端注册顺序和语义分组。

## 决策

- 策略只保存 `factor_candidate_refs`，角色绑定也保存 factor ref，不再用 alias 作为执行身份。
- `shared.factors` 是 ref 到 descriptor 的冻结表；descriptor 拥有 label、owner、family、参数和可选 Git revision 元数据。
- 执行前 Manager 把每个选定 ref 解析为真实 `Factor` 对象；回测运行时继续接收 Factor，不接收 alias 或 ref。
- 因子族目录只由因子创建/查看页面加载，不进入 workspace 或 RunSpec。内嵌上传的族源码作为保留 Run 输入放在 `temporary_objects.factor_families`；revision manifest 冻结可执行语义。
- RunSpec v3 删除 analysis/root family alias 和旧策略 alias 字段。旧版本 RunSpec 拒绝，不在运行时修复。
- 持久化和展示的 RunSpec JSON 保留后端注册顺序；只有身份哈希使用临时排序键编码。

## 后果

因子身份不随标签变化；chip 详情动作解析的对象与实际执行对象一致；冻结 RunSpec 只有一种规范因子表示。人类仍看到语义分组，内容哈希不受键顺序影响。已有 v1/v2 RunSpec 必须先预览并重新提交为 v3 才能运行。
