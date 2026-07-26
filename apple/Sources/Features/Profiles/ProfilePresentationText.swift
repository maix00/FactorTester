import Foundation

/// Localizes backend enum values at the presentation boundary while leaving
/// user-provided names, IDs, paths, and report prose untouched.
enum ProfilePresentationText {
    static func artifactStatus(_ value: String) -> String {
        localized(value, mappings: [
            "ready": "已就绪",
            "available": "可用",
            "pending": "等待处理",
            "missing": "缺失",
            "failed": "失败",
            "invalid": "无效",
        ])
    }

    static func initializationSourceMode(_ value: String) -> String {
        localized(value, mappings: [
            "registered": "已登记",
            "server_authorized": "服务器已授权",
            "authorized": "已授权",
            "local": "本地",
            "canonical": "canonical 因子库",
        ])
    }

    static func agentRole(_ value: String) -> String {
        localized(value, mappings: [
            "research": "研究 Agent",
            "planning": "规划 Agent",
            "execution": "执行 Agent",
            "agent": "Agent",
        ])
    }

    static func agentScope(_ value: String) -> String {
        localized(value, mappings: [
            "workspace": "工作区",
            "profile": "Profile",
            "global": "全局",
        ])
    }

    static func jobKind(_ value: String) -> String {
        localized(value, mappings: [
            "test": "测试任务",
            "backtest": "回测",
            "group_backtest": "分组回测",
            "ic": "IC 测试",
            "step": "Step 回测",
        ])
    }

    private static func localized(
        _ value: String,
        mappings: [String: String]
    ) -> String {
        guard let key = mappings[value.lowercased()] else { return value }
        return L10n.text(key)
    }
}
