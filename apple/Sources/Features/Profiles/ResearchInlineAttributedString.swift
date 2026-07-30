#if os(macOS)
import AppKit

enum ResearchInlineAttributedString {
    static func make(
        _ source: String,
        scope: ResearchDocumentReferenceScope = .init(
            componentID: "",
            bindings: []
        ),
        font: NSFont = NSFont.preferredFont(forTextStyle: .body)
    ) -> NSAttributedString {
        let result = NSMutableAttributedString()
        for segment in scope.presentationSegments(in: source) {
            switch segment {
            case let .text(value):
                result.append(markdown(value, font: font))
            case let .reference(reference):
                result.append(referenceText(reference, font: font))
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

    private static func referenceText(
        _ reference: ResearchDocumentTypedLink,
        font: NSFont
    ) -> NSAttributedString {
        let result = NSMutableAttributedString()
        if let icon = referenceIcon(reference, font: font) {
            result.append(icon)
        }
        result.append(NSMutableAttributedString(
            string: " \(reference.label)",
            attributes: [
                .font: font,
                .foregroundColor: ResearchDocumentTypedLinkPresentation.nsColor(
                    for: reference.kind
                ),
                .link: reference.url as Any,
                ResearchDocumentReferenceTextAttribute.label: reference.label,
            ]
        ))
        return result
    }

    private static func referenceIcon(
        _ reference: ResearchDocumentTypedLink,
        font: NSFont
    ) -> NSAttributedString? {
        guard let image = NSImage(
            systemSymbolName: ResearchDocumentTypedLinkPresentation.symbol(
                for: reference.kind
            ),
            accessibilityDescription: nil
        ) else {
            return nil
        }
        let attachment = NSTextAttachment()
        let side = ceil(font.pointSize)
        let size = NSImage.SymbolConfiguration(
            pointSize: font.pointSize * 0.9,
            weight: .regular
        )
        let tint = NSImage.SymbolConfiguration(
            hierarchicalColor: ResearchDocumentTypedLinkPresentation.nsColor(
                for: reference.kind
            )
        )
        attachment.image = image.withSymbolConfiguration(size.applying(tint))
        attachment.bounds = NSRect(
            x: 0,
            y: font.descender * 0.4,
            width: side,
            height: side
        )
        let result = NSMutableAttributedString(attachment: attachment)
        let range = NSRange(location: 0, length: result.length)
        result.addAttribute(.link, value: reference.url as Any, range: range)
        result.addAttribute(
            ResearchDocumentReferenceTextAttribute.label,
            value: reference.label,
            range: range
        )
        return result
    }
}

enum ResearchDocumentReferenceTextAttribute {
    static let label = NSAttributedString.Key(
        "com.gtht.factortester.reference-label"
    )
}
#endif
