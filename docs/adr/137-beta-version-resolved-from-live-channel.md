# ADR-137：Beta 版本号由可达服务器的频道清单递增

> **编号迁移说明：** 本文原文件名为 `098-beta-version-resolved-from-live-channel.md`。因 ADR-098 已用于
> App 管理 CLI 运行时，本文迁移为 ADR-137；决策内容不因重编号改变。

## 状态

已接受

## 背景

把 `0.1.3-beta.32` 写进 Xcode 项目会让开发构建、发布构建和服务器当前
状态脱节。发布同一版本时，Sparkle 还可能因为 `CFBundleVersion` 没有增加
而认为没有可安装更新。

## 决策

1. `apple/project.yml` 只保存开发版本（当前为 `0.1.3-dev`）和 build 下限，
   不保存某一次 Beta 的固定序号。
2. `factortester-manager client release --channel beta` 在构建前读取所有
   可达目标的 `beta.json`，并把本机已安装 FTClient 的 Beta 版本作为本地
   下限，取最高的 `X.Y.Z-beta.N`，生成 `N+1`。
3. Beta build 同样取已发现的最大 build 与项目 build 下限中的较大值，再加一。
4. 无法连接的服务器不阻塞版本解析，也不参与高水位计算；它恢复后由管理员
   明确再次执行发布。系统不做后台自动补发。服务器可达但清单损坏、签名错误
   或字段非法时必须失败。
5. 显式传入不高于已发现版本或 build 的值会被拒绝，避免覆盖已发布频道。
6. Stable 仍由 GitHub 发布，必须显式提供版本和 build；只有 Beta 使用自动递增。

## 后果

- Beta 版本不再需要人工维护 `beta.32` 之类的常量。
- 即使服务器清空或尚未发布 `beta.json`，本机已有的 Beta 客户端也不会被
  新发布的版本号回退覆盖。
- 多服务器并行发布前可以先得到一个一致的版本/build 身份。
- 离线节点不会阻塞在线节点的发布；管理员以后再次发布时必须沿用已记录的
  版本/build，不得为同一次补发重新生成新的 Beta 序号。
