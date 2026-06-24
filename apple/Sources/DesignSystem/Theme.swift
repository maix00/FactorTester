import SwiftUI

/// 统一的视觉令牌 —— 「一套通用方法固定前端用户的体验」的展示层基础。
/// 全部基于苹果原生材质/字体/系统色，macOS 与 iOS 自动适配明暗模式。
enum Theme {
    static let accent = Color.accentColor

    static let cardCorner: CGFloat = 14
    static let gridSpacing: CGFloat = 18
    static let cardMinWidth: CGFloat = 220

    /// 卡片背景：用系统分组背景，跨平台一致。
    static var cardBackground: Color {
        #if os(iOS)
        return Color(uiColor: .secondarySystemGroupedBackground)
        #else
        return Color(nsColor: .controlBackgroundColor)
        #endif
    }

    static var pageBackground: Color {
        #if os(iOS)
        return Color(uiColor: .systemGroupedBackground)
        #else
        return Color(nsColor: .windowBackgroundColor)
        #endif
    }
}
