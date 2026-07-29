import SwiftUI

struct RenderedMathFormulaView: View {
    let latex: String
    let fallback: String

    @State private var contentHeight: CGFloat = 72

    var body: some View {
        ResearchMathWebView(
            document: MathFormulaDocument.make(latex: latex, fallback: fallback),
            openReference: nil,
            contentHeight: $contentHeight
        )
        .frame(maxWidth: .infinity)
        .frame(height: min(max(contentHeight, 48), 420))
        .clipShape(RoundedRectangle(cornerRadius: 7))
        .accessibilityLabel(fallback)
    }
}

struct RenderedInlineMathTextView: View {
    let text: String

    @Environment(\.researchDocumentReferenceAction) private var openReference
    @State private var contentHeight: CGFloat = 36

    var body: some View {
        ResearchMathWebView(
            document: MathRichTextDocument.make(text),
            openReference: openReference,
            contentHeight: $contentHeight
        )
        .frame(maxWidth: .infinity)
        .frame(height: min(max(contentHeight, 28), 420))
        .accessibilityLabel(text)
    }
}
