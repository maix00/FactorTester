import SwiftUI

struct ResearchDocumentComponentView: View {
    let component: ResearchDocumentComponent
    let children: [ResearchDocumentComponent]
    let childrenByParent: [String: [ResearchDocumentComponent]]
    let componentBindings: [ResearchDocumentBinding]
    let bindingsByComponent: [String: [ResearchDocumentBinding]]
    let assets: [ResearchDocumentAsset]
    let reportRef: String
    var embeddedInSectionBridge = false
    var chapterDisclosureReset: ResearchReportSectionBridgeReset?

    var body: some View {
        Group {
            if embeddedInSectionBridge {
                componentContents
                    .padding(.horizontal, 10)
                    .padding(.bottom, 10)
            } else {
                regularComponent
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .environment(
            \.researchDocumentReferenceComponentID,
            component.id
        )
        .environment(\.researchDocumentReferenceBindings, componentBindings)
    }

    private var regularComponent: some View {
        VStack(alignment: .leading, spacing: 9) {
            if showsHeading, component.kind != "chapter" {
                heading
            }
            componentContents
        }
        .padding(component.kind == "chapter" ? 0 : 10)
    }

    private var heading: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            ResearchDocumentHeadingText(
                text: component.title,
                role: headingRole,
                componentID: component.id
            )
        }
    }

    @ViewBuilder
    private var componentContents: some View {
        if !component.bodyBlocks.isEmpty {
            ResearchDocumentRichTextView(blocks: component.bodyBlocks)
        }
        ResearchDocumentContentView(
            content: component.content,
            assets: assets,
            reportRef: reportRef
        )
        if ResearchDocumentComponentPresentation.isEmptyChapter(
            component, children: children
        ) {
            Label(L10n.text("本章节暂无内容"), systemImage: "doc.text")
                .foregroundStyle(.secondary)
                .padding(.vertical, 24)
                .frame(maxWidth: .infinity, alignment: .center)
        } else if !children.isEmpty {
            childList
        }
    }

    private var childList: some View {
        VStack(alignment: .leading, spacing: 9) {
            ForEach(ResearchReportChildGroup.group(children)) { group in
                ResearchReportSectionBridge(
                    components: group.components,
                    bindingsByComponent: bindingsByComponent,
                    reset: component.kind == "chapter"
                        ? chapterDisclosureReset : nil
                ) { child in
                    childComponent(
                        child,
                        embeddedInSectionBridge:
                            ResearchDocumentComponentPresentation
                                .usesSectionBridge(
                                    kind: child.kind,
                                    displayKind: child.displayKind
                                )
                    )
                }
            }
        }
    }

    private func childComponent(
        _ child: ResearchDocumentComponent,
        embeddedInSectionBridge: Bool = false
    ) -> some View {
        ResearchDocumentComponentView(
            component: child,
            children: childrenByParent[child.id] ?? [],
            childrenByParent: childrenByParent,
            componentBindings: bindingsByComponent[child.id] ?? [],
            bindingsByComponent: bindingsByComponent,
            assets: assets,
            reportRef: reportRef,
            embeddedInSectionBridge: embeddedInSectionBridge,
            chapterDisclosureReset: nil
        )
    }

    private var showsHeading: Bool {
        ResearchDocumentComponentPresentation.showsHeading(
            kind: component.kind,
            title: component.title,
            body: component.body,
            bodyBlocks: component.bodyBlocks,
            displayKind: component.displayKind
        )
    }

    private var headingRole: ResearchDocumentHeadingRole {
        switch component.kind {
        case "chapter": return .chapter
        case "section", "subsection", "special": return .section
        default: return .component
        }
    }

}

enum ResearchDocumentComponentPresentation {
    static func isEmptyChapter(
        _ component: ResearchDocumentComponent,
        children: [ResearchDocumentComponent]
    ) -> Bool {
        guard component.kind == "chapter",
              component.bodyBlocks.isEmpty,
              children.isEmpty else { return false }
        if case .none = component.content { return true }
        return false
    }

    static func usesSectionBridge(
        kind: String,
        displayKind: String = ""
    ) -> Bool {
        ["chapter", "section", "subsection", "special"].contains(kind)
            || isCollapsible(kind: kind, displayKind: displayKind)
    }

    static func showsHeading(
        kind: String,
        title: String,
        body: String,
        bodyBlocks: [ResearchDocumentTextBlock]? = nil,
        displayKind: String = ""
    ) -> Bool {
        guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return false }
        return isCollapsible(kind: kind, displayKind: displayKind)
            || !ResearchDocumentListPresentation.hidesInternalHeading(
                kind: kind,
                title: title,
                body: body,
                blocks: bodyBlocks
            )
    }

    static func isCollapsible(
        kind: String,
        displayKind: String = ""
    ) -> Bool {
        kind == "special" || (
            ["section", "subsection", "table"].contains(kind)
            && [
                "current_obligations",
                "obligation_requirement_coverage",
            ].contains(displayKind)
        )
    }
}
