import SwiftUI

struct ResearchRunSpecConfigurationView: View {
    enum Phase {
        case proposed
        case frozen

        var explanation: String {
            switch self {
            case .proposed:
                return "这是运行前形成的完整拟提交合同。"
                    + "研究者可以在执行前审查全部参数，并用 RunSpec 哈希核对提交前后是否一致。"
            case .frozen:
                return "这是服务器实际接受并用于执行的冻结配置。"
                    + "它是结果证据的身份与来源依据，不是统计结果本身。"
            }
        }

        var disclosureTitle: String {
            switch self {
            case .proposed: return "运行前拟提交配置（完整）"
            case .frozen: return "运行后冻结配置（完整）"
            }
        }
    }

    let phase: Phase
    let configurationJSON: String

    var body: some View {
        Text(phase.explanation)
            .font(.caption)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
        DisclosureGroup(phase.disclosureTitle) {
            ScrollView([.horizontal, .vertical]) {
                Text(configurationJSON)
                    .font(.caption.monospaced())
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 320)
            .padding(.top, 8)
        }
    }
}
