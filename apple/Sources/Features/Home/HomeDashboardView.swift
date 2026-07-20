import SwiftUI

struct HomeDashboardView: View {
    let modules: [Module]
    let isLoading: Bool
    let loadError: String?
    let openModule: (Module) -> Void
    let openAdapter: (ClientAdapterModel) -> Void
    let openTab: (ClientTab) -> Void

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
                ClientAdapterPanel(onOpen: openAdapter)
                LazyVGrid(columns: columns, spacing: Theme.gridSpacing) {
                    DashboardShortcutCard(
                        title: "研究进度",
                        description: "查看各 Profile 的实时步骤、义务与报告",
                        systemImage: "chart.xyaxis.line"
                    ) { openTab(.research) }
                    DashboardShortcutCard(
                        title: "Profiles",
                        description: "管理研究身份、工作区与初始化来源",
                        systemImage: "person.2.crop.square.stack"
                    ) { openTab(.profiles) }
                    DashboardShortcutCard(
                        title: "个人中心",
                        description: "账户、安全、产品组与因子库授权",
                        systemImage: "person.crop.circle"
                    ) { openTab(.account) }
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
                Text(title).font(.headline)
                Text(description)
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
                Text(module.title).font(.headline)
                Text(module.desc)
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
