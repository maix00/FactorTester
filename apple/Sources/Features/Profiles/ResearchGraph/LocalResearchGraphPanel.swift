import SwiftUI

struct LocalResearchGraphPanel: View {
    @ObservedObject var store: LocalResearchGraphStore
    let importFile: () -> Void

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label(
                        L10n.text("本地研究图"),
                        systemImage: "doc.badge.plus"
                    )
                    .font(.headline)
                    Spacer()
                    Button(L10n.text("导入 YAML"), action: importFile)
                        .buttonStyle(.bordered)
                }
                Text(L10n.text(
                    "文件保存在本机 Documents/FactorTester；不会自动上传服务器。用户文件不记录语言版本。"
                ))
                .font(.caption)
                .foregroundStyle(.secondary)
                Text(L10n.text(
                    "选择的默认研究图仅供本机 Research Agent 使用，不会自动上传"
                ))
                .font(.caption)
                .foregroundStyle(.secondary)
                if let errorMessage = store.errorMessage {
                    Text(errorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
                if store.files.isEmpty {
                    Text(L10n.text("尚无本地研究图"))
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(store.files) { file in
                        HStack(spacing: 8) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(file.name)
                                Text(file.filename)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            if store.defaultFileID == file.id {
                                Text(L10n.text("默认"))
                                    .font(.caption)
                                    .foregroundStyle(.tint)
                            } else {
                                Button(L10n.text("设为默认")) {
                                    store.setDefault(file)
                                }
                                .buttonStyle(.borderless)
                            }
                            Button(role: .destructive) {
                                store.delete(file)
                            } label: {
                                Image(systemName: "trash")
                            }
                            .buttonStyle(.borderless)
                            .accessibilityLabel(L10n.text("删除本地研究图"))
                        }
                        .padding(.vertical, 3)
                    }
                }
            }
        }
    }
}
