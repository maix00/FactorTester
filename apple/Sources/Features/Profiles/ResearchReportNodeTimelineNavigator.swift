import SwiftUI

struct ResearchReportNodeTimelineNavigator: View {
    let items: [ResearchReportNodeTimelineItem]
    @Binding var selectedComponentID: String
    let select: (ResearchReportNodeTimelineItem) -> Void

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(items) { item in
                        row(item)
                            .id(item.id)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 10)
            }
            .onChange(of: selectedComponentID) { componentID in
                guard !componentID.isEmpty else { return }
                withAnimation(.easeInOut(duration: 0.2)) {
                    proxy.scrollTo(componentID, anchor: .center)
                }
            }
        }
        .accessibilityIdentifier("research.report.node-timeline")
    }

    private func row(_ item: ResearchReportNodeTimelineItem) -> some View {
        Button { select(item) } label: {
            HStack(alignment: .top, spacing: 8) {
                Circle()
                    .fill(item.componentID == selectedComponentID
                        ? Color.accentColor : Color.secondary.opacity(0.45))
                    .frame(width: 6, height: 6)
                    .padding(.top, 7)
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.title)
                        .font(.callout.weight(
                            item.componentID == selectedComponentID
                                ? .semibold : .regular
                        ))
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    metadata(item)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 9)
            .padding(.vertical, 7)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                item.componentID == selectedComponentID
                    ? Color.accentColor.opacity(0.14) : .clear,
                in: RoundedRectangle(cornerRadius: 7, style: .continuous)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("research.report.node.\(item.componentID)")
        .help(item.title)
    }

    @ViewBuilder
    private func metadata(_ item: ResearchReportNodeTimelineItem) -> some View {
        let timestamp = ResearchReportNodeTimelineText.timestamp(item.timestamp)
        if !timestamp.isEmpty || !item.graphVersion.isEmpty {
            HStack(spacing: 5) {
                if !timestamp.isEmpty { Text(timestamp) }
                if !item.graphVersion.isEmpty { Text(item.graphVersion) }
            }
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
    }
}
