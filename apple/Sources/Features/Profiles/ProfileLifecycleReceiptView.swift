import SwiftUI

struct ProfileLifecycleReceiptView: View {
    let receipt: ProfileLifecycleReceipt
    @ObservedObject var controller: LocalProfileController

    var body: some View {
        GroupBox("最近一次设置结果") {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label(receipt.action, systemImage: "checkmark.seal")
                    Spacer()
                    Text(LocalizedStringKey(statusKey))
                        .foregroundStyle(.secondary)
                }
                if !receipt.profileID.isEmpty {
                    LabeledContent("Profile", value: receipt.profileID)
                }
                LabeledContent("Git 保留") {
                    if receipt.branchRetained && receipt.commitsRetained {
                        Text("分支与提交均保留")
                    } else {
                        Text("请检查 receipt")
                    }
                }
                if !receipt.receiptRef.isEmpty {
                    Text(receipt.receiptRef)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                if receipt.action == "delete" {
                    Button("清理已删除 Profile 的空目录") {
                        Task {
                            await controller.purgeProfile(receipt.profileID)
                        }
                    }
                    .help("只清理空的本地目录；不删除 Git 分支、提交或 receipt。")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(8)
        }
    }

    private var statusKey: String {
        guard !receipt.status.isEmpty else { return "已完成" }
        switch receipt.status.lowercased() {
        case "completed", "succeeded", "success": return "已完成"
        case "failed", "error": return "失败"
        default: return receipt.status
        }
    }
}
