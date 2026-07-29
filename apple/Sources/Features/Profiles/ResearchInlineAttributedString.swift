#if os(macOS)
import AppKit

enum ResearchInlineAttributedString {
    static let horizontalPadding = "\u{2005}"

    static func make(
        _ source: String,
        scope: ResearchDocumentReferenceScope = .init(
            componentID: "",
            bindings: []
        )
    ) -> NSAttributedString {
        let result = NSMutableAttributedString()
        for segment in scope.presentationSegments(in: source) {
            switch segment {
            case let .text(value):
                result.append(markdown(value))
            case let .reference(reference):
                result.append(referenceText(reference))
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

    private static func markdown(_ source: String) -> NSAttributedString {
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
            value: NSFont.preferredFont(forTextStyle: .body),
            range: NSRange(location: 0, length: rendered.length)
        )
        for range in codeRanges.reversed() {
            let attributes = codeAttributes()
            rendered.removeAttribute(.backgroundColor, range: range)
            rendered.addAttributes(attributes, range: range)
            rendered.insert(
                NSAttributedString(
                    string: horizontalPadding,
                    attributes: attributes
                ),
                at: NSMaxRange(range)
            )
            rendered.insert(
                NSAttributedString(
                    string: horizontalPadding,
                    attributes: attributes
                ),
                at: range.location
            )
        }
        return rendered
    }

    private static func codeAttributes() -> [NSAttributedString.Key: Any] {
        [
            .font: NSFont.monospacedSystemFont(
                ofSize: NSFont.preferredFont(forTextStyle: .body).pointSize,
                weight: .regular
            ),
            ResearchInlineCodeLayoutManager.attribute: true,
        ]
    }

    private static func referenceText(
        _ reference: ResearchDocumentTypedLink
    ) -> NSAttributedString {
        let result = NSMutableAttributedString()
        if let icon = referenceIcon(reference) {
            result.append(icon)
        }
        result.append(NSMutableAttributedString(
            string: " \(reference.label)",
            attributes: [
                .font: NSFont.preferredFont(forTextStyle: .body),
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
        _ reference: ResearchDocumentTypedLink
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
        let size = NSImage.SymbolConfiguration(pointSize: 12, weight: .regular)
        let tint = NSImage.SymbolConfiguration(
            hierarchicalColor: ResearchDocumentTypedLinkPresentation.nsColor(
                for: reference.kind
            )
        )
        attachment.image = image.withSymbolConfiguration(size.applying(tint))
        attachment.bounds = NSRect(x: 0, y: -2, width: 14, height: 14)
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
