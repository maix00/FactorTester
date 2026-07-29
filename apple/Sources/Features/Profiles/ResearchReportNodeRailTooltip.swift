import SwiftUI

struct ResearchReportNodeRailTooltip: View {
    let item: ResearchReportNodeTimelineItem

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(item.title)
                .font(.callout.weight(.semibold))
                .lineLimit(1)
            if !item.preview.isEmpty {
                Text(item.preview)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
            let metadata = ResearchReportNodeRailMetrics.metadata(item)
            if !metadata.isEmpty {
                Text(metadata)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(
            cornerRadius: 12,
            style: .continuous
        ))
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.primary.opacity(0.1), lineWidth: 0.5)
        }
        .shadow(color: .black.opacity(0.16), radius: 14, y: 5)
    }
}

enum ResearchReportNodeRailMetrics {
    static func markerScale(
        index: Int,
        targetIndex: Int?
    ) -> CGFloat {
        guard let targetIndex else { return 0.2308 }
        let progress: CGFloat = switch abs(index - targetIndex) {
        case 0: 1
        case 1: 0.7
        case 2: 0.4
        case 3: 0.2
        default: 0
        }
        return 0.2308 + (0.7692 * progress)
    }

    static func metadata(
        _ item: ResearchReportNodeTimelineItem
    ) -> String {
        [
            ResearchReportNodeTimelineText.timestamp(item.timestamp),
            item.graphVersion,
        ].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    static func accessibilityLabel(
        _ item: ResearchReportNodeTimelineItem
    ) -> String {
        [item.title, metadata(item)]
            .filter { !$0.isEmpty }
            .joined(separator: "，")
    }

    static func tooltipY(
        markerY: CGFloat,
        availableHeight: CGFloat
    ) -> CGFloat {
        max(8, min(markerY - 46, availableHeight - 126))
    }
}
