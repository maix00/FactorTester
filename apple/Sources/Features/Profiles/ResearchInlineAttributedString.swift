#if os(macOS)
import AppKit

enum ResearchInlineAttributedString {
    static func make(
        _ source: String,
        scope: ResearchDocumentReferenceScope = .init(
            componentID: "",
            bindings: []
        ),
        font: NSFont = NSFont.preferredFont(forTextStyle: .body),
        mathImages: [String: ResearchInlineMathRendered] = [:]
    ) -> NSAttributedString {
        let result = NSMutableAttributedString()
        for segment in scope.presentationSegments(in: source) {
            switch segment {
            case let .text(value):
                result.append(richText(
                    value,
                    font: font,
                    mathImages: mathImages
                ))
            case let .reference(reference):
                result.append(ResearchInlineAttachments.reference(
                    reference,
                    font: font
                ))
            }
        }
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineSpacing = ResearchDocumentTextMetrics.lineSpacing
        paragraph.lineBreakMode = .byWordWrapping
        result.addAttribute(
            .paragraphStyle,
            value: paragraph,
            range: NSRange(location: 0, length: result.length)
        )
        return result
    }

    private static func richText(
        _ source: String,
        font: NSFont,
        mathImages: [String: ResearchInlineMathRendered]
    ) -> NSAttributedString {
        let result = NSMutableAttributedString()
        for token in ResearchInlineMathTokens.parse(source) {
            switch token {
            case let .text(value):
                result.append(ResearchInlineCodeAttributedString.make(
                    value,
                    font: font
                ))
            case let .formula(latex):
                result.append(ResearchInlineAttachments.math(
                    latex,
                    font: font,
                    rendered: mathImages[
                        ResearchInlineMathImageRenderer.key(
                            latex: latex,
                            fontSize: font.pointSize
                        )
                    ]
                ))
            }
        }
        return result
    }

}
#endif
