import SwiftUI

/// 把一个模块解析成具体页面。
///
/// 这是「写一个原生页就少一个 web 回落」的接缝：在 `nativeView(for:)` 里为某个
/// 模块 id 返回原生实现即可；未实现的自动回落到 `WebPageView`（转发到 web 版本）。
struct ModuleDestinationView: View {
    let module: Module

    var body: some View {
        Group {
            if let native = Self.nativeView(for: module) {
                native
            } else {
                WebPageView(path: module.path)
            }
        }
        .navigationTitle(module.title)
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
    }

    /// 已迁移为原生的模块在此登记；返回 nil 表示回落到 web。
    /// 目前首页已原生；其余模块沿用 web，迁移时在此 `case` 中 return AnyView(...) 即可。
    static func nativeView(for module: Module) -> AnyView? {
        switch module.id {
        // case "single_factor_test": return AnyView(SingleFactorTestView())
        default: return nil
        }
    }
}
