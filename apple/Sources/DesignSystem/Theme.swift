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

struct SettingsPageHeader: View {
    let title: String
    let subtitle: String
    let systemImage: String?

    init(title: String, subtitle: String, systemImage: String? = nil) {
        self.title = title
        self.subtitle = subtitle
        self.systemImage = systemImage
    }

    var body: some View {
        HStack(spacing: 16) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(.system(size: 30, weight: .medium))
                    .foregroundStyle(.tint)
                    .frame(width: 56, height: 56)
                    .background(.tint.opacity(0.12), in: RoundedRectangle(cornerRadius: 14))
            }
            VStack(alignment: .leading, spacing: 5) {
                Text(title).font(.largeTitle.weight(.semibold))
                Text(subtitle).foregroundStyle(.secondary)
            }
        }
    }
}

struct SettingsPageShell<Content: View>: View {
    let title: String
    let subtitle: String
    let systemImage: String
    @ViewBuilder let content: () -> Content

    init(
        title: String,
        subtitle: String,
        systemImage: String,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.title = title
        self.subtitle = subtitle
        self.systemImage = systemImage
        self.content = content
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                SettingsPageHeader(
                    title: title,
                    subtitle: subtitle,
                    systemImage: systemImage
                )
                content()
            }
            .frame(maxWidth: 680, alignment: .leading)
            .padding(28)
        }
    }
}

struct SettingsRow<Control: View>: View {
    let title: String
    let description: String
    @ViewBuilder let control: () -> Control

    init(
        title: String,
        description: String,
        @ViewBuilder control: @escaping () -> Control
    ) {
        self.title = title
        self.description = description
        self.control = control
    }

    var body: some View {
        HStack(alignment: .top, spacing: 18) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.body.weight(.medium))
                Text(description)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            control()
                .frame(minWidth: 180, alignment: .trailing)
        }
        .padding(.vertical, 8)
    }
}

struct SettingsSectionCard<Content: View>: View {
    let title: String
    @ViewBuilder let content: () -> Content

    init(_ title: String, @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.content = content
    }

    var body: some View {
        SettingsCard(title) {
            VStack(alignment: .leading, spacing: 0) {
                content()
            }
        }
    }
}

struct SettingsRefreshButton: View {
    let title: String
    let isWorking: Bool
    let action: () -> Void

    init(_ title: String = "刷新", isWorking: Bool = false, action: @escaping () -> Void) {
        self.title = title
        self.isWorking = isWorking
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            if isWorking {
                ProgressView().controlSize(.small)
            } else {
                Label(title, systemImage: "arrow.clockwise")
            }
        }
        .buttonStyle(.bordered)
        .disabled(isWorking)
    }
}

struct SettingsCard<Content: View>: View {
    let title: String?
    @ViewBuilder let content: () -> Content

    init(_ title: String? = nil, @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.content = content
    }

    var body: some View {
        GroupBox {
            content().padding(8)
        } label: {
            if let title { Text(title).font(.headline) }
        }
    }
}
