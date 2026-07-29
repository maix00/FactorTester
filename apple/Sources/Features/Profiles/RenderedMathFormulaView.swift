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
    @Environment(\.researchDocumentReferenceComponentID) private var componentID
    @Environment(\.researchDocumentReferenceBindings) private var bindings
    @State private var contentHeight: CGFloat = 36

    var body: some View {
        ResearchMathWebView(
            document: MathRichTextDocument.make(
                text,
                trustedReferenceKeys: referenceScope.webTrustedReferenceKeys
            ),
            openReference: {
                guard let trusted = referenceScope.trusted($0) else { return }
                openReference(trusted)
            },
            contentHeight: $contentHeight
        )
        .frame(maxWidth: .infinity)
        .frame(height: min(max(contentHeight, 28), 420))
        .accessibilityLabel(text)
    }

    private var referenceScope: ResearchDocumentReferenceScope {
        .init(componentID: componentID, bindings: bindings)
    }
}
