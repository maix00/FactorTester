import SwiftUI

struct ResearchDocumentComponentView: View {
    let component: ResearchDocumentComponent
    let children: [ResearchDocumentComponent]
    let childrenByParent: [String: [ResearchDocumentComponent]]
    let assets: [ResearchDocumentAsset]
    let reportRef: String

    @State private var expanded = false

    var body: some View {
        LazyVStack(alignment: .leading, spacing: 9) {
            heading
            if !component.body.isEmpty {
                ResearchDocumentRichTextView(text: component.body)
            }
            contentView
            if !children.isEmpty {
                childView
            }
        }
        .padding(component.kind == "chapter" ? 16 : 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(background, in: RoundedRectangle(cornerRadius: 10))
    }

    private var heading: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            Text(component.title)
                .font(component.kind == "chapter" ? .title2.weight(.semibold) : .headline)
            if component.kind == "special", !component.displayKind.isEmpty {
                Text(component.displayKind)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 3)
                    .background(Color.secondary.opacity(0.1), in: Capsule())
            }
        }
    }

    @ViewBuilder
    private var contentView: some View {
        switch component.content {
        case .none:
            EmptyView()
        case let .text(value):
            ResearchDocumentRichTextView(text: value)
        case let .code(language, source):
            ResearchDocumentCodeView(language: language, source: source)
        case let .math(latex, fallback):
            VStack(alignment: .leading, spacing: 6) {
                RenderedMathFormulaView(latex: latex, fallback: fallback)
                Text(fallback.isEmpty ? latex : fallback)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        case let .table(columns, rows):
            ResearchDocumentTableView(columns: columns, rows: rows)
        case let .image(assetRef):
            if let asset = assets.first(where: { $0.assetRef == assetRef }) {
                ResearchDocumentAssetView(asset: asset, reportRef: reportRef)
            } else {
                Label("研究图像生成物缺失", systemImage: "photo.badge.exclamationmark")
                    .foregroundStyle(.secondary)
            }
        case let .json(value):
            ResearchDocumentCodeView(language: "json", source: value)
        }
    }

    @ViewBuilder
    private var childView: some View {
        if component.kind == "chapter" {
            childList
        } else {
            DisclosureGroup(isExpanded: $expanded) {
                childList
                    .padding(.top, 5)
            } label: {
                Text(expanded ? "收起子项" : "展开子项（\(children.count)）")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Color.accentColor)
            }
        }
    }

    private var childList: some View {
        LazyVStack(alignment: .leading, spacing: 9) {
            ForEach(children) { child in
                ResearchDocumentComponentView(
                    component: child,
                    children: childrenByParent[child.id] ?? [],
                    childrenByParent: childrenByParent,
                    assets: assets,
                    reportRef: reportRef
                )
            }
        }
    }

    private var background: Color {
        component.kind == "chapter"
            ? Color.secondary.opacity(0.045)
            : Color.secondary.opacity(0.025)
    }
}

struct ResearchDocumentRichTextView: View {
    let text: String

    var body: some View {
        let blocks = ResearchDocumentParser.textBlocks(text)
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                switch block {
                case let .text(value):
                    prose(value)
                case let .table(columns, rows):
                    ResearchDocumentTableView(columns: columns, rows: rows)
                }
            }
        }
    }

    @ViewBuilder
    private func prose(_ value: String) -> some View {
        if ResearchReportTextProjection.containsMath(value) {
            RenderedInlineMathTextView(text: value)
        } else {
            Text(markdown(value)).textSelection(.enabled)
        }
    }

    private func markdown(_ value: String) -> AttributedString {
        (try? AttributedString(markdown: value, options: .init(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        ))) ?? AttributedString(value)
    }
}

struct ResearchDocumentCodeView: View {
    let language: String
    let source: String

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(language)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            ScrollView([.horizontal, .vertical]) {
                Text(source)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
            }
            .frame(maxHeight: 260)
            .background(Color.black.opacity(0.045), in: RoundedRectangle(cornerRadius: 7))
        }
    }
}
