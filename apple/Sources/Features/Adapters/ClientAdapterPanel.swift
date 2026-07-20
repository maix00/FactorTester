import SwiftUI

struct ClientAdapterPanel: View {
    let onOpen: (ClientAdapterModel) -> Void
    @StateObject private var controller = ClientAdapterController()

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if !controller.adapters.isEmpty {
                HStack {
                    Label("本地研究", systemImage: "desktopcomputer")
                        .font(.headline)
                    Spacer()
                    if controller.isWorking {
                        ProgressView().controlSize(.small)
                    } else {
                        Button {
                            Task { await controller.refresh() }
                        } label: {
                            Image(systemName: "arrow.clockwise")
                        }
                        .buttonStyle(.plain)
                        .help("刷新本地组件")
                    }
                }
                LazyVGrid(
                    columns: [
                        GridItem(
                            .adaptive(minimum: Theme.cardMinWidth),
                            spacing: Theme.gridSpacing
                        )
                    ],
                    spacing: Theme.gridSpacing
                ) {
                    ForEach(controller.adapters) { adapter in
                        adapterCard(adapter)
                    }
                }
            }
            if let error = controller.error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.footnote)
                    .foregroundStyle(.red)
            }
        }
        .task { await controller.refresh() }
        .onChange(of: controller.openTarget?.id) { _ in
            if let adapter = controller.openTarget {
                onOpen(adapter)
                controller.openTarget = nil
            }
        }
    }

    private func adapterCard(_ adapter: ClientAdapterModel) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "chart.xyaxis.line")
                    .font(.title2)
                    .foregroundStyle(.tint)
                Spacer()
                statusBadge(adapter)
            }
            Text(adapter.displayName)
                .font(.headline)
            Text("版本 \(adapter.version)")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Button(adapter.running ? "停止" : "启动") {
                    Task { await controller.toggle(adapter) }
                }
                .disabled(
                    controller.isWorking
                        || (adapter.healthy && !adapter.running)
                )
                Spacer()
                Button("在 App 中打开") {
                    Task { await controller.open(adapter) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(controller.isWorking || adapter.uiURL == nil)
            }
        }
        .padding(18)
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardCorner))
        .overlay {
            RoundedRectangle(cornerRadius: Theme.cardCorner)
                .strokeBorder(.separator, lineWidth: 0.5)
        }
    }

    private func statusBadge(_ adapter: ClientAdapterModel) -> some View {
        let label = adapter.running
            ? (adapter.healthy ? "运行中" : "启动中")
            : (adapter.healthy ? "外部服务可用" : "已停止")
        let color: Color = adapter.healthy
            ? .green
            : (adapter.running ? .orange : .secondary)
        return Text(label)
            .font(.caption.weight(.medium))
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(color.opacity(0.12), in: Capsule())
    }
}
