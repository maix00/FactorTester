import SwiftUI

enum ResearchReportChapterDisclosureMode: Equatable {
    case defaultExpanded
    case collapsed
}

struct ResearchReportSectionBridgeReset: Equatable {
    let mode: ResearchReportChapterDisclosureMode
    let revision: Int
}

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
    let bindingsByComponent: [String: [ResearchDocumentBinding]]
    let reset: ResearchReportSectionBridgeReset?
    private let content: (ResearchDocumentComponent) -> Content
    @State private var expandedIDs: Set<String>
    @State private var restoreTask: Task<Void, Never>?
    @Environment(\.researchReportScrollAnchorCoordinator)
    private var scrollAnchorCoordinator

    init(
        components: [ResearchDocumentComponent],
        bindingsByComponent: [String: [ResearchDocumentBinding]] = [:],
        reset: ResearchReportSectionBridgeReset? = nil,
        @ViewBuilder content: @escaping (
            ResearchDocumentComponent
        ) -> Content
    ) {
        self.components = components
        self.bindingsByComponent = bindingsByComponent
        self.reset = reset
        self.content = content
        _expandedIDs = State(initialValue:
            ResearchReportSectionBridgePresentation.expandedIDs(
                components, mode: reset?.mode ?? .collapsed
            )
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(components) { component in
                VStack(alignment: .leading, spacing: 0) {
                    if usesSectionBridge(component) {
                        ResearchReportSectionHeader(
                            component: component,
                            bindings: bindingsByComponent[component.id] ?? [],
                            specialKind: specialKind(component),
                            isExpanded: expandedIDs.contains(component.id),
                            toggle: { toggle(component.id) }
                        )
                        if expandedIDs.contains(component.id) {
                            content(component)
                                .padding(.leading, 20)
                        }
                    } else {
                        // Entries, tables and lists are report components, not
                        // nested sections. Their generated structural labels
                        // (正文/表格/列表) must never acquire a disclosure row
                        // merely because the component sits in the report tree.
                        content(component)
                            .padding(.leading, containsSectionBridge ? 20 : 0)
                    }
                }
            }
        }
        .overlay(alignment: .leading) {
            if containsSectionBridge {
                Rectangle()
                    .fill(Color.secondary.opacity(0.24))
                    .frame(width: 1)
                    .padding(.leading, 5.5)
                    .padding(.vertical, 16)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(
            "research.report.section.bridge.\(components.first?.id ?? "empty")"
        )
        .onChange(of: reset) { value in
            guard let value else { return }
            expandedIDs = ResearchReportSectionBridgePresentation.expandedIDs(
                components, mode: value.mode
            )
        }
        .onDisappear {
            restoreTask?.cancel()
            restoreTask = nil
        }
    }

    private func specialKind(
        _ component: ResearchDocumentComponent
    ) -> ResearchReportSectionSpecialKind? {
        ResearchReportSectionSpecialKind.resolve(
            component: component,
            bindings: bindingsByComponent[component.id] ?? []
        )
    }

    private func usesSectionBridge(
        _ component: ResearchDocumentComponent
    ) -> Bool {
        ResearchDocumentComponentPresentation.usesSectionBridge(
            kind: component.kind,
            displayKind: component.displayKind
        )
    }

    private var containsSectionBridge: Bool {
        ResearchReportSectionBridgePresentation.containsSectionBridge(
            components
        )
    }

    private func toggle(_ componentID: String) {
        restoreTask?.cancel()
        let snapshot = scrollAnchorCoordinator?.captureLayout()
        var transaction = Transaction()
        transaction.disablesAnimations = true
        withTransaction(transaction) {
            if expandedIDs.contains(componentID) {
                expandedIDs.remove(componentID)
            } else {
                expandedIDs.insert(componentID)
            }
        }
        restoreTask = Task { @MainActor in
            await scrollAnchorCoordinator?.restoreLayout(snapshot)
        }
    }
}

enum ResearchReportSectionBridgePresentation {
    static func containsSectionBridge(
        _ components: [ResearchDocumentComponent]
    ) -> Bool {
        components.contains {
            ResearchDocumentComponentPresentation.usesSectionBridge(
                kind: $0.kind,
                displayKind: $0.displayKind
            )
        }
    }

    static func expandedIDs(
        _ components: [ResearchDocumentComponent],
        mode: ResearchReportChapterDisclosureMode
    ) -> Set<String> {
        guard mode == .defaultExpanded else { return [] }
        return Set(components.compactMap { component in
            ResearchDocumentComponentPresentation.isCollapsible(
                kind: component.kind,
                displayKind: component.displayKind
            ) ? nil : component.id
        })
    }
}
