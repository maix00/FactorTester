import SwiftUI

struct ClientSidebar: View {
    @EnvironmentObject private var releaseController: ClientReleaseController
    @Binding var selection: String
    let openTabs: [ClientTab]
    let open: (ClientTab) -> Void
    let close: (ClientTab) -> Void

    var body: some View {
        List(selection: $selection) {
            Section("功能入口") {
                launcher(.home)
                launcher(.research)
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
                bottomLauncher(.account)
                bottomLauncher(.settings)
            }
            .padding(.vertical, 6)
        }
        .frame(minWidth: 210)
    }

    private func launcher(_ tab: ClientTab) -> some View {
        Label(tab.title, systemImage: tab.systemImage)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .onTapGesture { open(tab) }
            .tag(tab.id)
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { open(tab) }
            .accessibilityIdentifier("sidebar.launch.\(tab.id)")
    }

    private func bottomLauncher(_ tab: ClientTab) -> some View {
        HStack(spacing: 6) {
            Button { open(tab) } label: {
                Label(tab.title, systemImage: tab.systemImage)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if tab.id == ClientTab.settings.id {
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
                Task { await releaseController.restartToApply() }
            } label: {
                updateBadge("重启更新", color: .orange)
            }
            .buttonStyle(.plain)
            .help("重启 FTClient 并完成更新")
            .accessibilityIdentifier("sidebar.update.restart")
        } else if releaseController.isWorking {
            updateBadge("正在准备", color: .secondary)
                .accessibilityIdentifier("sidebar.update.preparing")
        } else if releaseController.hasAvailableUpdate {
            Button {
                Task { await releaseController.update() }
            } label: {
                updateBadge("有新版本", color: .blue)
            }
            .buttonStyle(.plain)
            .help("下载并准备 \(releaseController.latestVersion)")
            .accessibilityIdentifier("sidebar.update.available")
        }
    }

    private func updateBadge(_ title: String, color: Color) -> some View {
        Text(title)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 3)
            .background(color.opacity(0.12), in: Capsule())
    }

    private func openedRow(_ tab: ClientTab) -> some View {
        HStack(spacing: 8) {
            Label(tab.title, systemImage: tab.systemImage)
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
