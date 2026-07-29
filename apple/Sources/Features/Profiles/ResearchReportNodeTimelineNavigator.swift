import SwiftUI

struct ResearchReportNodeTimelineNavigator: View {
    let items: [ResearchReportNodeTimelineItem]
    @Binding var selectedComponentID: String
    @Binding var pendingComponentID: String
    let select: (
        ResearchReportNodeTimelineItem,
        ResearchReportNavigationBehavior
    ) -> Void

    @State private var hoveredComponentID: String?
    @State private var scrubComponentID: String?
    @State private var rowFrames: [String: CGRect] = [:]
    @FocusState private var focusedComponentID: String?

    var body: some View {
        GeometryReader { outer in
            let maximumHeight = min(outer.size.height * 0.7, 640)
            let contentHeight = CGFloat(max(items.count, 1)) * 14
            let railHeight = min(contentHeight, maximumHeight)

            ScrollViewReader { proxy in
                VStack(spacing: 0) {
                    Spacer(minLength: 0)
                    if contentHeight > maximumHeight {
                        ScrollView(.vertical) {
                            rows
                        }
                        .scrollIndicators(.hidden)
                        .mask(verticalFadeMask(enabled: true))
                    } else {
                        rows
                    }
                    Spacer(minLength: 0)
                }
                .frame(width: 42, height: railHeight)
                .frame(
                    width: 48,
                    height: outer.size.height,
                    alignment: .center
                )
                .onChange(of: selectedComponentID) { _ in
                    centerCurrentItem(proxy)
                }
                .onChange(of: pendingComponentID) { _ in
                    centerCurrentItem(proxy)
                }
            }
            .overlay(alignment: .topLeading) {
                if let item = tooltipItem,
                   let frame = rowFrames[item.componentID] {
                    ResearchReportNodeRailTooltip(item: item)
                        .frame(width: 320)
                        .offset(
                            x: 44,
                            y: ResearchReportNodeRailMetrics.tooltipY(
                                markerY: frame.midY,
                                availableHeight: outer.size.height
                            )
                        )
                        .transition(.opacity.combined(with: .scale(
                            scale: 0.98, anchor: .leading
                        )))
                        .allowsHitTesting(false)
                }
            }
        }
        .frame(width: 48)
        .coordinateSpace(name: "research.report.node-rail")
        .onPreferenceChange(ResearchReportRailRowFrameKey.self) {
            rowFrames = $0
        }
        .animation(.easeOut(duration: 0.16), value: interactionTargetID)
        .animation(.easeOut(duration: 0.15), value: tooltipItem?.id)
        .accessibilityIdentifier("research.report.node-timeline")
    }

    private var rows: some View {
        LazyVStack(spacing: 0) {
            ForEach(Array(items.enumerated()), id: \.element.id) {
                index, item in
                row(item, at: index)
                    .id(item.id)
            }
        }
        .contentShape(Rectangle())
        .simultaneousGesture(scrubGesture)
    }

    private func row(
        _ item: ResearchReportNodeTimelineItem,
        at index: Int
    ) -> some View {
        Button {
            select(item, .smooth)
        } label: {
            HStack(spacing: 0) {
                Capsule()
                    .fill(markerColor(for: item))
                    .frame(width: 26, height: 2)
                    .scaleEffect(
                        x: markerScale(at: index),
                        y: 1,
                        anchor: .leading
                    )
                Spacer(minLength: 0)
            }
            .frame(width: 40, height: 14)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .focused($focusedComponentID, equals: item.componentID)
        .onHover { hovering in
            if hovering {
                hoveredComponentID = item.componentID
            } else if hoveredComponentID == item.componentID {
                hoveredComponentID = nil
            }
        }
        .background {
            GeometryReader { proxy in
                Color.clear.preference(
                    key: ResearchReportRailRowFrameKey.self,
                    value: [
                        item.componentID: proxy.frame(
                            in: .named("research.report.node-rail")
                        ),
                    ]
                )
            }
        }
        .accessibilityLabel(
            ResearchReportNodeRailMetrics.accessibilityLabel(item)
        )
        .accessibilityValue(
            item.componentID == selectedComponentID
                ? L10n.text("当前节点") : ""
        )
        .accessibilityIdentifier(
            "research.report.node.\(item.componentID)"
        )
    }

    private var scrubGesture: some Gesture {
        DragGesture(
            minimumDistance: 2,
            coordinateSpace: .named("research.report.node-rail")
        )
        .onChanged { value in
            guard let item = nearestItem(to: value.location.y),
                  scrubComponentID != item.componentID else { return }
            scrubComponentID = item.componentID
            select(item, .instant)
        }
        .onEnded { _ in
            scrubComponentID = nil
        }
    }

    private func nearestItem(to y: CGFloat) -> ResearchReportNodeTimelineItem? {
        items.filter {
            rowFrames[$0.componentID] != nil
        }.min { lhs, rhs in
            abs((rowFrames[lhs.componentID]?.midY ?? 0) - y)
                < abs((rowFrames[rhs.componentID]?.midY ?? 0) - y)
        }
    }

    private var interactionTargetID: String? {
        scrubComponentID
            ?? hoveredComponentID
            ?? focusedComponentID
            ?? (selectedComponentID.isEmpty ? nil : selectedComponentID)
    }

    private func markerScale(at index: Int) -> CGFloat {
        let targetIndex = interactionTargetID.flatMap { targetID in
            items.firstIndex(
                where: { $0.componentID == targetID }
            )
        }
        return ResearchReportNodeRailMetrics.markerScale(
            index: index,
            targetIndex: targetIndex
        )
    }

    private func markerColor(
        for item: ResearchReportNodeTimelineItem
    ) -> Color {
        if item.componentID == selectedComponentID {
            return .primary
        }
        if item.componentID == interactionTargetID {
            return .secondary.opacity(0.75)
        }
        return .secondary.opacity(0.35)
    }

    private var tooltipItem: ResearchReportNodeTimelineItem? {
        let id = scrubComponentID ?? hoveredComponentID ?? focusedComponentID
        return items.first { $0.componentID == id }
    }

    private func centerCurrentItem(_ proxy: ScrollViewProxy) {
        let id = pendingComponentID.isEmpty
            ? selectedComponentID : pendingComponentID
        guard !id.isEmpty else { return }
        withAnimation(.easeInOut(duration: 0.16)) {
            proxy.scrollTo(id, anchor: .center)
        }
    }

    @ViewBuilder
    private func verticalFadeMask(enabled: Bool) -> some View {
        if enabled {
            LinearGradient(
                stops: [
                    .init(color: .clear, location: 0),
                    .init(color: .black, location: 0.08),
                    .init(color: .black, location: 0.92),
                    .init(color: .clear, location: 1),
                ],
                startPoint: .top,
                endPoint: .bottom
            )
        } else {
            Color.black
        }
    }
}

private struct ResearchReportRailRowFrameKey: PreferenceKey {
    static var defaultValue: [String: CGRect] = [:]

    static func reduce(
        value: inout [String: CGRect],
        nextValue: () -> [String: CGRect]
    ) {
        value.merge(nextValue(), uniquingKeysWith: { _, latest in latest })
    }
}
