import SwiftUI

struct HomeDashboardView: View {
    let modules: [Module]
    let isLoading: Bool
    let loadError: String?
    let networkInfo: ManagerNetworkInfo?
    let networkError: String?
    let openModule: (Module) -> Void
    let openAdapter: (ClientAdapterModel) -> Void
    let openResearch: () -> Void

    private let columns = [
        GridItem(
            .adaptive(minimum: Theme.cardMinWidth),
            spacing: Theme.gridSpacing
        )
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                welcome
                managerNetworkPanel
                LazyVGrid(columns: columns, spacing: Theme.gridSpacing) {
                    DashboardShortcutCard(
                        title: "研究进度",
                        description: "查看各 Profile 的实时步骤、义务与报告",
                        systemImage: "chart.xyaxis.line"
                    ) { openResearch() }
                    ForEach(modules) { module in
                        ModuleCard(module: module) {
                            openModule(module)
                        }
                    }
                }
                if isLoading {
                    ProgressView().frame(maxWidth: .infinity)
                } else if let loadError {
                    Label(
                        loadError,
                        systemImage: "exclamationmark.triangle.fill"
                    )
                    .font(.footnote)
                    .foregroundStyle(.red)
                }
                ClientAdapterPanel(onOpen: openAdapter)
            }
            .padding(20)
        }
        .background(Theme.pageBackground)
    }

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("FactorTester")
                .font(.largeTitle.weight(.semibold))
            Text("选择研究模块；每个工作现场会在左侧保持。")
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private var managerNetworkPanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(L10n.text("服务器网络信息"), systemImage: "network")
                .font(.headline)
            if let networkInfo {
                networkRow(
                    L10n.text("当前 Manager"),
                    "\(networkInfo.serverID) · \(networkInfo.role)"
                )
                networkRow(
                    L10n.text("内网服务器地址"),
                    networkInfo.internalEndpointSummary.isEmpty
                        ? L10n.text("尚未由服务器提供")
                        : networkInfo.internalEndpointSummary
                )
                networkRow(
                    L10n.text("当前或推断的公网服务器"),
                    networkInfo.publicEndpointSummary.isEmpty
                        ? L10n.text("尚未由服务器提供")
                        : networkInfo.publicEndpointSummary
                )
            } else if let networkError {
                Text(networkError)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                ProgressView().controlSize(.small)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(
            cornerRadius: Theme.cardCorner,
            style: .continuous
        ))
        .overlay {
            RoundedRectangle(cornerRadius: Theme.cardCorner)
                .strokeBorder(.separator, lineWidth: 0.5)
        }
    }

    private func networkRow(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.footnote.weight(.medium))
                .textSelection(.enabled)
        }
    }
}

struct DashboardShortcutCard: View {
    let title: String
    let description: String
    let systemImage: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 10) {
                Image(systemName: systemImage)
                    .font(.system(size: 28))
                    .foregroundStyle(Theme.accent)
                Text(L10n.resource(title)).font(.headline)
                Text(L10n.resource(description))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
            .background(Theme.cardBackground)
            .clipShape(RoundedRectangle(
                cornerRadius: Theme.cardCorner, style: .continuous
            ))
            .overlay {
                RoundedRectangle(cornerRadius: Theme.cardCorner)
                    .strokeBorder(.separator, lineWidth: 0.5)
            }
        }
        .buttonStyle(.plain)
    }
}

struct ModuleCard: View {
    let module: Module
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 10) {
                icon
                Text(L10n.resource(module.title)).font(.headline)
                Text(L10n.resource(module.desc))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
            .background(Theme.cardBackground)
            .clipShape(
                RoundedRectangle(
                    cornerRadius: Theme.cardCorner,
                    style: .continuous
                )
            )
            .overlay {
                RoundedRectangle(cornerRadius: Theme.cardCorner)
                    .strokeBorder(.separator, lineWidth: 0.5)
            }
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var icon: some View {
        if let symbol = module.sfSymbol, !symbol.isEmpty {
            Image(systemName: symbol)
                .font(.system(size: 28))
                .foregroundStyle(Theme.accent)
                .frame(height: 32)
        } else {
            Text(module.icon).font(.system(size: 28)).frame(height: 32)
        }
    }
}
