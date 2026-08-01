import SwiftUI

struct ResearchReportChildGroup: Identifiable {
    let id: String
    let components: [ResearchDocumentComponent]

    var componentIDs: [String] { components.map(\.id) }

    static func group(
        _ components: [ResearchDocumentComponent]
    ) -> [ResearchReportChildGroup] {
        guard let first = components.first else { return [] }
        return [ResearchReportChildGroup(
            id: "section-bridge-\(first.id)",
            components: components
        )]
    }
}

struct ResearchReportSectionBridge<Content: View>: View {
    let components: [ResearchDocumentComponent]
    private let content: (ResearchDocumentComponent) -> Content
    @State private var expandedIDs: Set<String>

    init(
        components: [ResearchDocumentComponent],
        @ViewBuilder content: @escaping (
            ResearchDocumentComponent
        ) -> Content
    ) {
        self.components = components
        self.content = content
        _expandedIDs = State(initialValue:
            ResearchReportSectionBridgePresentation.initiallyExpandedIDs(
                components
            )
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(components) { component in
                VStack(alignment: .leading, spacing: 0) {
                    Button {
                        withAnimation(.easeInOut(duration: 0.18)) {
                            if expandedIDs.contains(component.id) {
                                expandedIDs.remove(component.id)
                            } else {
                                expandedIDs.insert(component.id)
                            }
                        }
                    } label: {
                        HStack(alignment: .top, spacing: 8) {
                            bridgeMarker
                            Image(systemName: specialKind(component)?.icon
                                ?? "doc.text")
                                .foregroundStyle(
                                    specialKind(component)?.tint ?? .secondary
                                )
                                .frame(width: 16, height: 20)
                            Text(component.title)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(.primary)
                                .multilineTextAlignment(.leading)
                                .fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 0)
                            Image(systemName: expandedIDs.contains(component.id)
                                ? "chevron.down" : "chevron.right")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)
                                .padding(.top, 3)
                        }
                        .padding(.vertical, 8)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    if expandedIDs.contains(component.id) {
                        content(component)
                            .padding(.leading, 20)
                    }
                }
            }
        }
        .overlay(alignment: .leading) {
            Rectangle()
                .fill(Color.secondary.opacity(0.24))
                .frame(width: 1)
                .padding(.leading, 5.5)
                .padding(.vertical, 16)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(
            "research.report.section.bridge.\(components.first?.id ?? "empty")"
        )
    }

    private var bridgeMarker: some View {
        Circle()
            .fill(Color.secondary.opacity(0.42))
            .frame(width: 7, height: 7)
            .padding(.top, 15)
            .frame(width: 12)
            .zIndex(1)
    }

    private func specialKind(
        _ component: ResearchDocumentComponent
    ) -> ResearchReportSectionSpecialKind? {
        ResearchReportSectionSpecialKind.resolve(
            displayKind: component.displayKind,
            sectionRole: nil,
            hasObligationChanges: component.displayKind == "obligation_changes"
        )
    }
}

enum ResearchReportSectionBridgePresentation {
    static func initiallyExpandedIDs(
        _ components: [ResearchDocumentComponent]
    ) -> Set<String> {
        Set(components.compactMap { component in
            ResearchDocumentComponentPresentation.isCollapsible(
                kind: component.kind,
                displayKind: component.displayKind
            ) ? nil : component.id
        })
    }
}
