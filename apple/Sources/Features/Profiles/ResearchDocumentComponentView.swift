import SwiftUI

struct ResearchDocumentComponentView: View {
    let component: ResearchDocumentComponent
    let children: [ResearchDocumentComponent]
    let childrenByParent: [String: [ResearchDocumentComponent]]
    let componentBindings: [ResearchDocumentBinding]
    let bindingsByComponent: [String: [ResearchDocumentBinding]]
    let assets: [ResearchDocumentAsset]
    let reportRef: String

    @State private var expanded = false

    var body: some View {
        Group {
            if isCollapsible {
                collapsedSection
            } else {
                regularComponent
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background {
            if component.kind == "chapter" {
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color.secondary.opacity(0.045))
            }
        }
        .environment(
            \.researchDocumentReferenceComponentID,
            component.id
        )
        .environment(\.researchDocumentReferenceBindings, componentBindings)
    }

    private var regularComponent: some View {
        LazyVStack(alignment: .leading, spacing: 9) {
            if showsHeading {
                heading
            }
            componentContents
        }
        .padding(component.kind == "chapter" ? 16 : 10)
    }

    private var collapsedSection: some View {
        LazyVStack(alignment: .leading, spacing: 8) {
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
                font: component.kind == "chapter"
                    ? .title2.weight(.semibold) : .headline,
                componentID: component.id
            )
            if let specialKind {
                Label(specialKind.title, systemImage: specialKind.icon)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(specialKind.tint)
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
        LazyVStack(alignment: .leading, spacing: 9) {
            ForEach(children) { child in
                ResearchDocumentComponentView(
                    component: child,
                    children: childrenByParent[child.id] ?? [],
                    childrenByParent: childrenByParent,
                    componentBindings: bindingsByComponent[child.id] ?? [],
                    bindingsByComponent: bindingsByComponent,
                    assets: assets,
                    reportRef: reportRef
                )
            }
        }
    }

    private var isCollapsible: Bool {
        ["section", "subsection", "special"].contains(component.kind)
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
}
