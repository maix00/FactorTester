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
        .background(background, in: RoundedRectangle(cornerRadius: 10))
    }

    private var regularComponent: some View {
        LazyVStack(alignment: .leading, spacing: 9) {
            heading
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
            ResearchDocumentInlineTextView(text: component.title)
                .font(component.kind == "chapter" ? .title2.weight(.semibold) : .headline)
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
        contentView
        if !children.isEmpty { childList }
    }

    @ViewBuilder
    private var contentView: some View {
        switch component.content {
        case .none:
            EmptyView()
        case let .text(value):
            ResearchDocumentRichTextView(text: value)
        case let .code(language, source):
            ClientCodeBlock(source: source, language: language)
        case let .math(latex, fallback):
            VStack(alignment: .leading, spacing: 6) {
                RenderedMathFormulaView(latex: latex, fallback: fallback)
                if !fallback.isEmpty {
                    Text(fallback).font(.callout).foregroundStyle(.secondary)
                }
            }
        case let .table(columns, rows, source):
            ResearchDocumentTableView(columns: columns, rows: rows, source: source)
        case let .image(assetRef):
            if let asset = assets.first(where: { $0.assetRef == assetRef }) {
                ResearchDocumentAssetView(asset: asset, reportRef: reportRef)
            } else {
                Label(L10n.text("研究图像生成物缺失"),
                      systemImage: "photo.badge.exclamationmark")
                    .foregroundStyle(.secondary)
            }
        case let .json(value):
            ClientCodeBlock(source: value, language: "json")
        }
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

    private var background: Color {
        component.kind == "chapter"
            ? Color.secondary.opacity(0.045)
            : Color.secondary.opacity(0.025)
    }
}
