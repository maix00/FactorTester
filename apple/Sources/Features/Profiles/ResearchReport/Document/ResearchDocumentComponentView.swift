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

    @State private var chapterDisclosureMode =
        ResearchReportChapterDisclosureMode.defaultExpanded
    @State private var chapterDisclosureRevision = 0

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
        .background {
            if component.kind == "chapter" {
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color.accentColor.opacity(0.045))
            }
        }
        .environment(
            \.researchDocumentReferenceComponentID,
            component.id
        )
        .environment(\.researchDocumentReferenceBindings, componentBindings)
    }

    private var regularComponent: some View {
        VStack(alignment: .leading, spacing: 9) {
            if showsHeading {
                heading
            }
            componentContents
        }
        .padding(component.kind == "chapter" ? 16 : 10)
    }

    private var heading: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            ResearchDocumentHeadingText(
                text: component.title,
                role: headingRole,
                componentID: component.id
            )
            if component.kind == "chapter" {
                Spacer(minLength: 8)
                Button(action: toggleChapterDisclosure) {
                    Image(systemName: chapterDisclosureMode == .defaultExpanded
                        ? "chevron.up" : "chevron.down")
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
                .help(L10n.text(
                    chapterDisclosureMode == .defaultExpanded
                        ? "收起本章第一层小节"
                        : "恢复本章默认展开状态"
                ))
                .accessibilityLabel(L10n.text(
                    chapterDisclosureMode == .defaultExpanded
                        ? "收起本章第一层小节"
                        : "恢复本章默认展开状态"
                ))
            }
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
        if !children.isEmpty { childList }
    }

    private var childList: some View {
        VStack(alignment: .leading, spacing: 9) {
            ForEach(ResearchReportChildGroup.group(children)) { group in
                ResearchReportSectionBridge(
                    components: group.components,
                    bindingsByComponent: bindingsByComponent,
                    reset: component.kind == "chapter" ? .init(
                        mode: chapterDisclosureMode,
                        revision: chapterDisclosureRevision
                    ) : nil
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
            embeddedInSectionBridge: embeddedInSectionBridge
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

    private func toggleChapterDisclosure() {
        withAnimation(.easeInOut(duration: 0.18)) {
            chapterDisclosureMode = (
                chapterDisclosureMode == .defaultExpanded
                    ? .collapsed : .defaultExpanded
            )
            chapterDisclosureRevision &+= 1
        }
    }
}

enum ResearchDocumentComponentPresentation {
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
