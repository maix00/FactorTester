import SwiftUI

struct HomeDashboardView: View {
    let modules: [Module]
    let isLoading: Bool
    let loadError: String?
    let openModule: (Module) -> Void
    let openAdapter: (ClientAdapterModel) -> Void

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
            Text("选择研究模块；每个模块会在独立 Tab 中保持自己的环境。")
                .foregroundStyle(.secondary)
        }
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
