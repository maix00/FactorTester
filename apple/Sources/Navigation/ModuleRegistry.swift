import Foundation
import Combine

/// 首页模块的运行时来源 —— 从服务器拉取共享注册表并暴露给 SwiftUI。
///
/// 与 web 端 `loadModules()` 读取的是同一个 `/static/config/modules.json`，
/// 因此「一处写注册，所有客户端的 home 都能看到」。
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
            loadError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
        isLoading = false
    }

    /// 当前用户角色下应展示的模块。
    func visibleModules(forRole role: String?) -> [Module] {
        modules.filter { $0.isVisible(forRole: role) }
    }
}
