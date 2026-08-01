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

    @State private var expanded = false
    @State private var chapterDisclosureMode =
        ResearchReportChapterDisclosureMode.defaultExpanded
    @State private var chapterDisclosureRevision = 0

    var body: some View {
        Group {
            if embeddedInSectionBridge {
                componentContents
                    .padding(.horizontal, 10)
                    .padding(.bottom, 10)
            } else if isCollapsible {
                collapsedSection
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

    private var collapsedSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            ResearchReportSectionDisclosureHeader(
                title: component.title,
                subtitle: sectionSubtitle,
                specialKind: specialKind,
                isExpanded: expanded,
                action: { withAnimation(.easeInOut(duration: 0.18)) { expanded.toggle() } }
            )
            if expanded { componentContents }
        }
        .padding(10)
    }

    private var heading: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            ResearchDocumentHeadingText(
                text: component.title,
                role: component.kind == "chapter" ? .chapter : .section,
                componentID: component.id
            )
            if let specialKind {
                Label(specialKind.title, systemImage: specialKind.icon)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(specialKind.tint)
            }
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
        if !component.body.isEmpty { ResearchDocumentRichTextView(text: component.body) }
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
                    childComponent(child, embeddedInSectionBridge: true)
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

    private var isCollapsible: Bool {
        ResearchDocumentComponentPresentation.isCollapsible(
            kind: component.kind,
            displayKind: component.displayKind
        )
    }

    private var specialKind: ResearchReportSectionSpecialKind? {
        ResearchReportSectionSpecialKind.resolve(
            displayKind: component.displayKind,
            sectionRole: nil,
            hasObligationChanges: component.kind == "special"
                && componentBindings.contains(where: { $0.kind == "obligation" })
        )
    }

    private var sectionSubtitle: String {
        specialKind?.title ?? L10n.text("点击查看内容")
    }

    private var showsHeading: Bool {
        !ResearchDocumentListPresentation.hidesInternalHeading(
            kind: component.kind,
            title: component.title,
            body: component.body
        )
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
    static func isCollapsible(
        kind: String,
        displayKind: String = ""
    ) -> Bool {
        kind == "special" || (
            kind == "table"
            && [
                "current_obligations",
                "obligation_requirement_coverage",
            ].contains(displayKind)
        )
    }
}
