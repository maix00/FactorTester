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

/// Text used by the shared settings chrome. String literals are catalog keys;
/// server values and already-formatted dynamic messages must opt into
/// `verbatim` so user data is never looked up as a translation key.
struct SettingsDisplayText: View, ExpressibleByStringLiteral {
    private enum Storage {
        case localized(LocalizedStringResource)
        case verbatim(String)
    }

    private let storage: Storage

    init(stringLiteral value: String) {
        storage = .localized(L10n.resource(value))
    }

    init(_ value: String) {
        storage = .localized(L10n.resource(value))
    }

    init(verbatim value: String) {
        storage = .verbatim(value)
    }

    var textValue: Text {
        switch storage {
        case let .localized(resource): Text(resource)
        case let .verbatim(value): Text(verbatim: value)
        }
    }

    static func verbatim(_ value: String) -> SettingsDisplayText {
        SettingsDisplayText(verbatim: value)
    }

    var body: some View {
        switch storage {
        case let .localized(resource): Text(resource)
        case let .verbatim(value): Text(verbatim: value)
        }
    }
}

struct SettingsPageHeader: View {
    let title: SettingsDisplayText
    let subtitle: SettingsDisplayText
    let systemImage: String?

    init(title: SettingsDisplayText, subtitle: SettingsDisplayText, systemImage: String? = nil) {
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
                title.font(.largeTitle.weight(.semibold))
                subtitle.foregroundStyle(.secondary)
            }
        }
    }
}

struct SettingsPageShell<Content: View>: View {
    let title: SettingsDisplayText
    let subtitle: SettingsDisplayText
    let systemImage: String
    @ViewBuilder let content: () -> Content

    init(
        title: SettingsDisplayText,
        subtitle: SettingsDisplayText,
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
    let title: SettingsDisplayText
    let description: SettingsDisplayText
    @ViewBuilder let control: () -> Control

    init(
        title: SettingsDisplayText,
        description: SettingsDisplayText,
        @ViewBuilder control: @escaping () -> Control
    ) {
        self.title = title
        self.description = description
        self.control = control
    }

    var body: some View {
        HStack(alignment: .top, spacing: 18) {
            VStack(alignment: .leading, spacing: 2) {
                title
                    .font(.body.weight(.medium))
                description
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
    let title: SettingsDisplayText
    @ViewBuilder let content: () -> Content

    init(_ title: SettingsDisplayText, @ViewBuilder content: @escaping () -> Content) {
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
    let title: SettingsDisplayText
    let isWorking: Bool
    let action: () -> Void

    init(_ title: SettingsDisplayText = "刷新", isWorking: Bool = false, action: @escaping () -> Void) {
        self.title = title
        self.isWorking = isWorking
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            if isWorking {
                ProgressView().controlSize(.small)
            } else {
                Label {
                    title
                } icon: {
                    Image(systemName: "arrow.clockwise")
                }
            }
        }
        .buttonStyle(.bordered)
        .disabled(isWorking)
    }
}

struct SettingsEditableText: View {
    @Binding var value: String
    let placeholder: SettingsDisplayText
    let onCommit: () -> Void
    @State private var editing = false

    init(
        value: Binding<String>,
        placeholder: SettingsDisplayText,
        onCommit: @escaping () -> Void = {}
    ) {
        _value = value
        self.placeholder = placeholder
        self.onCommit = onCommit
    }

    var body: some View {
        Group {
            if editing {
                TextField(text: $value, prompt: placeholder.textValue) {
                    EmptyView()
                }
                    .textFieldStyle(.roundedBorder)
                    .onSubmit {
                        editing = false
                        onCommit()
                    }
            } else {
                Button {
                    editing = true
                } label: {
                    Group {
                        if value.isEmpty {
                            placeholder
                        } else {
                            Text(verbatim: value)
                        }
                    }
                    .foregroundStyle(value.isEmpty ? .secondary : .primary)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("点击修改")
            }
        }
        .frame(minWidth: 180, alignment: .trailing)
    }
}

struct SettingsCard<Content: View>: View {
    let title: SettingsDisplayText?
    @ViewBuilder let content: () -> Content

    init(_ title: SettingsDisplayText? = nil, @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.content = content
    }

    var body: some View {
        GroupBox {
            content().padding(8)
        } label: {
            if let title { title.font(.headline) }
        }
    }
}
