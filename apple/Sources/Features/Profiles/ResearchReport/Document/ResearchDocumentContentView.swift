import SwiftUI

struct ResearchDocumentContentView: View {
    let content: ResearchDocumentContent
    let assets: [ResearchDocumentAsset]
    let reportRef: String

    @ViewBuilder
    var body: some View {
        switch content {
        case .none:
            EmptyView()
        case let .text(value):
            ResearchDocumentRichTextView(blocks: value.blocks)
        case let .code(language, source):
            ClientCodeBlock(source: source, language: language)
        case let .math(latex, fallback):
            VStack(alignment: .leading, spacing: 6) {
                RenderedMathFormulaView(latex: latex, fallback: fallback)
                if !fallback.isEmpty {
                    Text(fallback)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }
        case let .list(items):
            ResearchDocumentListView(items: items)
        case let .table(columns, rows, source):
            ResearchDocumentTableView(
                columns: columns,
                rows: rows,
                source: source
            )
        case let .image(assetRef):
            image(assetRef)
        case let .json(value):
            ClientCodeBlock(source: value, language: "json")
        }
    }

    @ViewBuilder
    private func image(_ assetRef: String) -> some View {
        if let asset = assets.first(where: { $0.assetRef == assetRef }) {
            ResearchDocumentAssetView(asset: asset, reportRef: reportRef)
        } else {
            Label(
                L10n.text("研究图像生成物缺失"),
                systemImage: "photo.badge.exclamationmark"
            )
            .foregroundStyle(.secondary)
        }
    }
}
