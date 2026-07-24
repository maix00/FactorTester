import SwiftUI

struct ResearchEntryResolutionGroups {
    let reviewed: [ResearchEntryRequirementItem]
    let referenceOnly: [ResearchEntryRequirementItem]
    let unresolved: [ResearchEntryRequirementItem]
    let reused: [ResearchEntryRequirementItem]
}

enum ResearchEntryResolutionPresentation {
    static func groups(
        _ value: ResearchEntryResolutionDelta
    ) -> ResearchEntryResolutionGroups {
        ResearchEntryResolutionGroups(
            reviewed: value.items.filter {
                ["assessed_pass", "assessed_limited", "not_applicable"]
                    .contains($0.resolutionStatus)
            },
            referenceOnly: value.items.filter {
                $0.resolutionStatus == "reference_only"
            },
            unresolved: value.items.filter {
                $0.resolutionStatus == "unresolved"
            },
            reused: value.items.filter {
                $0.resolutionStatus == "reused"
            }
        )
    }

    static func changeLabel(_ value: String) -> String? {
        switch value {
        case "added": return "新增要求"
        case "revised": return "语义已修订"
        case "metadata_only": return "说明已更新"
        default: return nil
        }
    }

    static func statusLabel(_ value: String) -> String {
        switch value {
        case "assessed_pass": return "本次审查通过"
        case "assessed_limited": return "有限通过"
        case "reused": return "沿用既有验证"
        case "reference_only": return "旧证据仅供参考"
        case "unresolved": return "尚未解决"
        case "not_applicable": return "本次不适用"
        default: return "状态未知"
        }
    }
}

struct ResearchEntryResolutionView: View {
    let value: ResearchEntryResolutionDelta

    private var groups: ResearchEntryResolutionGroups {
        ResearchEntryResolutionPresentation.groups(value)
    }

    var body: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: 10) {
                if value.reason == "graph_continuation" {
                    Text("这里只列出本次图版本变化触及的要求；既有研究结论和未变化义务不会重复汇报。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                itemGroup(groups.reviewed, tint: .blue)
                itemGroup(groups.referenceOnly, tint: .orange)
                itemGroup(groups.unresolved, tint: .red)
                if !groups.reused.isEmpty {
                    DisclosureGroup("沿用既有验证（\(groups.reused.count)）") {
                        itemGroup(groups.reused, tint: .secondary)
                            .padding(.top, 6)
                    }
                    .font(.caption.weight(.medium))
                }
            }
            .padding(.top, 8)
        } label: {
            HStack(spacing: 7) {
                Image(systemName: value.reason == "graph_continuation"
                    ? "arrow.triangle.branch" : "checkmark.shield")
                Text(value.reason == "graph_continuation"
                    ? "图版本升级准入审查" : "节点准入审查")
                    .font(.subheadline.weight(.semibold))
            }
        }
        .padding(12)
        .background(
            Color.secondary.opacity(0.055),
            in: RoundedRectangle(cornerRadius: 10)
        )
        .accessibilityIdentifier("research.entry-resolution")
    }

    @ViewBuilder
    private func itemGroup(
        _ items: [ResearchEntryRequirementItem],
        tint: Color
    ) -> some View {
        ForEach(items) { item in
            HStack(alignment: .top, spacing: 8) {
                Circle()
                    .fill(tint)
                    .frame(width: 6, height: 6)
                    .padding(.top, 6)
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.titleZh)
                        .font(.callout)
                    HStack(spacing: 6) {
                        if let change = ResearchEntryResolutionPresentation
                            .changeLabel(item.changeKind) {
                            Text(change)
                        }
                        Text(ResearchEntryResolutionPresentation.statusLabel(
                            item.resolutionStatus
                        ))
                    }
                    .font(.caption)
                    .foregroundStyle(tint)
                }
            }
        }
    }
}
