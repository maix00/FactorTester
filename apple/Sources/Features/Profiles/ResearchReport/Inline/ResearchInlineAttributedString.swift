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
        let segments = scope.presentationSegments(in: source)
        for index in segments.indices {
            let segment = segments[index]
            switch segment {
            case let .text(value):
                result.append(richText(
                    value,
                    font: font,
                    mathImages: mathImages
                ))
            case let .reference(reference):
                if ResearchDocumentLinkBoundarySpacing.needsLeadingSpace(
                    in: segments,
                    at: index
                ) {
                    result.append(linkBoundarySpace(font: font))
                }
                result.append(ResearchInlineAttachments.reference(
                    reference,
                    font: font
                ))
                if ResearchDocumentLinkBoundarySpacing.needsTrailingSpace(
                    in: segments,
                    at: index
                ) {
                    result.append(linkBoundarySpace(font: font))
                }
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

    private static func linkBoundarySpace(font: NSFont) -> NSAttributedString {
        NSAttributedString(
            string: ResearchDocumentLinkBoundarySpacing.value,
            attributes: [.font: font]
        )
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
