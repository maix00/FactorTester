import SwiftUI

struct ClientSidebar: View {
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var releaseController: ClientReleaseController
    @EnvironmentObject private var languageStore: LanguageStore
    @Binding var selection: String
    let openTabs: [ClientTab]
    let open: (ClientTab) -> Void
    let close: (ClientTab) -> Void
    @State private var showRestartPrompt = false

    var body: some View {
        List(selection: $selection) {
            Section("功能入口") {
                launcher(.home)
                launcher(.research)
                launcher(.jobs)
                launcher(.factorLibrary)
                launcher(.products)
                launcher(.profiles)
            }
            if !openTabs.filter(\.isClosable).isEmpty {
                Section("已打开") {
                    ForEach(openTabs.filter(\.isClosable)) { tab in
                        openedRow(tab)
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("FTClient")
        .safeAreaInset(edge: .bottom, spacing: 0) {
            VStack(spacing: 0) {
                Divider()
                bottomLauncher(.accountSettings)
            }
            .padding(.vertical, 6)
        }
        .alert("更新已准备好", isPresented: $showRestartPrompt) {
            Button("稍后", role: .cancel) {}
            Button("重启并更新") {
                Task { await releaseController.restartToApply() }
            }
        } message: {
            Text("更新已下载并验证，重启 FTClient 后完成安装。")
        }
        .frame(minWidth: 210)
    }

    private func launcher(_ tab: ClientTab) -> some View {
        Label {
            Text(verbatim: localizedTitle(for: tab))
        } icon: {
            Image(systemName: tab.systemImage)
        }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .onTapGesture { selection = tab.id }
            .tag(tab.id)
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { selection = tab.id }
            .accessibilityIdentifier("sidebar.launch.\(tab.id)")
    }

    private func bottomLauncher(_ tab: ClientTab) -> some View {
        HStack(spacing: 6) {
            Button { open(tab) } label: {
                Label {
                    if tab.id == ClientTab.accountSettings.id {
                        Text(verbatim: accountTitle)
                    } else {
                        Text(verbatim: localizedTitle(for: tab))
                    }
                } icon: {
                    Image(systemName: tab.systemImage)
                }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if tab.id == ClientTab.accountSettings.id {
                updateAction
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(
            selection == tab.id
                ? Color.accentColor.opacity(0.14) : Color.clear,
            in: RoundedRectangle(cornerRadius: 7)
        )
        .padding(.horizontal, 8)
        .accessibilityIdentifier("sidebar.launch.\(tab.id)")
    }

    @ViewBuilder
    private var updateAction: some View {
        if releaseController.isUpdateReady {
            Button {
                showRestartPrompt = true
            } label: {
                updateIcon("arrow.clockwise.circle.fill", color: .orange)
            }
            .buttonStyle(.plain)
            .help("更新已准备好；重启后安装")
            .accessibilityIdentifier("sidebar.update.restart")
        } else if releaseController.hasAvailableUpdate {
            Button {
                Task { await releaseController.update() }
            } label: {
                updateIcon("arrow.down.circle.fill", color: .blue)
            }
            .buttonStyle(.plain)
            .help(L10n.format("有更新：下载并准备 %@", releaseController.latestVersion))
            .accessibilityIdentifier("sidebar.update.available")
        }
    }

    private var accountTitle: String {
        session.user?.username.flatMap { $0.isEmpty ? nil : $0 }
            ?? L10n.text("设置", language: languageStore.selection)
    }

    private func localizedTitle(for tab: ClientTab) -> String {
        guard let key = tab.titleKey else { return tab.title }
        return L10n.text(key, language: languageStore.selection)
    }

    private func updateIcon(_ systemImage: String, color: Color) -> some View {
        Image(systemName: systemImage)
            .font(.callout.weight(.semibold))
            .foregroundStyle(color)
            .frame(width: 22, height: 22)
            .contentShape(Rectangle())
    }

    private func openedRow(_ tab: ClientTab) -> some View {
        HStack(spacing: 8) {
            Label {
                Text(verbatim: localizedTitle(for: tab))
            } icon: {
                Image(systemName: tab.systemImage)
            }
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: 4)
            Button { close(tab) } label: {
                Image(systemName: "xmark")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .help("关闭")
        }
        .contentShape(Rectangle())
        .onTapGesture { selection = tab.id }
        .tag(tab.id)
        .accessibilityIdentifier("sidebar.open.\(tab.id)")
    }
}
