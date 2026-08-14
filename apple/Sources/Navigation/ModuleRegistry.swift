import Foundation
import Combine

/// 首页模块的运行时来源 —— 从 Manager 拉取按会话过滤的导航注册表。
///
/// Manager 暂时不可用时使用最小显示回退，回退只保证已有入口可见，
/// 不承担服务端权限判断。
@MainActor
final class ModuleRegistry: ObservableObject {

    @Published private(set) var modules: [Module] = []
    @Published private(set) var isLoading = false
    @Published private(set) var loadError: String?

    func reload() async {
        isLoading = true
        loadError = nil
        do {
            modules = try await APIClient.shared.modules()
        } catch {
            modules = Module.fallbackModules
            loadError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
        isLoading = false
    }

    /// 当前会话应展示的模块。
    ///
    /// Manager 返回的目录已经完成权限过滤；这里额外检查认证状态，
    /// 仅用于 Manager 暂时不可用时的本地回退目录，不会成为权限来源。
    func visibleModules(forRole role: String?, isAuthenticated: Bool = false) -> [Module] {
        modules.filter {
            (!$0.requiresAuth || isAuthenticated) && $0.isVisible(forRole: role)
        }
    }
}
