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
                result.append(markdown(value, font: font))
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

    private static func markdown(
        _ source: String,
        font: NSFont
    ) -> NSAttributedString {
        let value = ResearchDocumentInlineTextStyle.markdown(source)
        var codeRanges: [NSRange] = []
        let characters = value.characters
        for run in value.runs {
            let start = characters.distance(
                from: characters.startIndex,
                to: run.range.lowerBound
            )
            let length = characters.distance(
                from: run.range.lowerBound,
                to: run.range.upperBound
            )
            if run.inlinePresentationIntent?.contains(.code) == true {
                codeRanges.append(NSRange(location: start, length: length))
            }
        }
        let rendered = NSMutableAttributedString(
            attributedString: NSAttributedString(value)
        )
        rendered.addAttribute(
            .font,
            value: font,
            range: NSRange(location: 0, length: rendered.length)
        )
        for range in codeRanges.reversed() {
            let attributes = codeAttributes(font: font)
            rendered.removeAttribute(.backgroundColor, range: range)
            rendered.addAttributes(attributes, range: range)
        }
        return rendered
    }

    private static func codeAttributes(
        font: NSFont
    ) -> [NSAttributedString.Key: Any] {
        [
            .font: NSFont.monospacedSystemFont(
                ofSize: font.pointSize,
                weight: .regular
            ),
            ResearchInlineCodeLayoutManager.attribute: true,
        ]
    }

}
#endif
