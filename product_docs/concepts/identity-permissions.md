## 身份、角色与授权 {#identity-and-permissions}

Keycloak 是身份认证和权限决策的权威。Manager 验证 Keycloak 会话，并使用短时会话投影处理请求；该投影不是可独立编辑的第二份用户或权限目录。

用户身份、平台客户端角色、Realm Group 组织层级和 Fine-Grained Admin Permissions（FGAP）解决不同问题。登录成功只证明用户完成认证，不代表可以管理机构、下载桌面运行包、登记设备或读取任意业务对象。对象的读取和写入仍由目标 Manager 按当前主体及对象权限判断。

一个用户可以有多个研究 Profile。Profile 是研究身份，不替代 Keycloak subject；显示名称、邮箱或用户 alias 也不能作为跨 Manager 自动合并身份的依据。

## 设备授权与本机运行包 {#device-policy}

CLI 首次登录可以使用 OAuth 设备授权。CLI 发起申请并显示一次性用户码；用户在浏览器核对目标 Manager、应用和用户码后批准。CLI 随后还要向同一 Manager 验证 issuer、subject 和准入权限，成功后才保存该端点的会话。设备授权流程只批准本轮登录，不会自动注册计算节点或开放对象写入。

设备自动登录白名单和本机安装包下载是独立策略。设备登记绑定来源 Manager、用户、客户端类型和设备公钥；每个 Manager 分别授权。撤销后，应按当前策略重新判断，不能因为旧 token 或登记记录存在就继续放行。

桌面安装包由单独的 Keycloak 客户端角色控制。获得下载权限只允许读取经过签名校验的本机包，不会把个人电脑注册为 Manager 调度节点，也不授权 Manager 调用用户的本机进程。

## 跨 Manager 身份同步 {#identity-sync}

身份同步按用户和授权方向执行。只有来源机构允许同步、用户具备相应公网登录权限且目标 Manager 完成身份核验时，目标端才可建立其身份投影。不得无条件复制整套机构目录、密码或 MFA 凭据。

机构内网离线时，内网 Keycloak 按本地规则独立认证；跨 Manager 同步恢复后，应处理带版本的变更并显式报告冲突。组织隔离由 Manager 服务端校验，不能仅靠前端过滤列表；没有覆盖的入口仍属于待补齐的授权边界。

## 管理入口 {#administration}

管理员从 React /app 的“管理员功能”进入受限操作；用户、机构、角色和 FGAP 规则由 Keycloak 管理。TradeResearch 页面只调用授权后的管理接口，不保存另一套可写的权限表。
