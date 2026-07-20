import SwiftUI

struct ClientReleaseStatusCard: View {
    @ObservedObject var controller: ClientReleaseController

    var body: some View {
        GroupBox {
            HStack(spacing: 0) {
                metric(
                    title: "当前版本",
                    value: fallback(controller.installedVersion),
                    icon: "shippingbox"
                )
                divider
                metric(
                    title: "可用版本",
                    value: fallback(controller.latestVersion),
                    icon: "arrow.down.circle"
                )
                divider
                healthMetric
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 10)
        } label: {
            HStack {
                Text("版本状态")
                Spacer()
                if controller.isWorking {
                    ProgressView()
                        .controlSize(.small)
                    Text("正在检查")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Button {
                        Task { await controller.refresh() }
                    } label: {
                        Label("刷新", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var healthMetric: some View {
        let healthy = controller.healthy == true
            && controller.compatible != false
        return metric(
            title: "运行状态",
            value: statusLabel,
            icon: healthy ? "checkmark.seal.fill" : "questionmark.circle",
            tint: healthy ? .green : .secondary
        )
    }

    private var statusLabel: String {
        if controller.healthy == false { return L10n.text("需要修复") }
        if controller.compatible == false { return L10n.text("协议不兼容") }
        if controller.healthy == true { return L10n.text("正常") }
        return L10n.text("尚未检查")
    }

    private var divider: some View {
        Divider().frame(height: 50)
    }

    private func metric(
        title: String,
        value: String,
        icon: String,
        tint: Color = .accentColor
    ) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(tint)
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.headline)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 16)
    }

    private func fallback(_ value: String) -> String {
        value.isEmpty ? L10n.text("未安装") : value
    }
}
