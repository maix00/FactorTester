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
                    Text(receipt.status.isEmpty ? "completed" : receipt.status)
                        .foregroundStyle(.secondary)
                }
                if !receipt.profileID.isEmpty {
                    LabeledContent("Profile", value: receipt.profileID)
                }
                LabeledContent(
                    "Git 保留",
                    value: receipt.branchRetained && receipt.commitsRetained
                        ? "分支与提交均保留" : "请检查 receipt"
                )
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
}
