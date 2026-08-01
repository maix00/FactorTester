#if os(macOS)
import AppKit

enum ResearchInlineAttachments {
    static func math(
        _ latex: String,
        font: NSFont,
        rendered: ResearchInlineMathRendered?
    ) -> NSAttributedString {
        guard let rendered else {
            return NSAttributedString(
                string: latex,
                attributes: [
                    .font: NSFontManager.shared.convert(
                        font,
                        toHaveTrait: .italicFontMask
                    )
                ]
            )
        }
        let attachment = NSTextAttachment()
        attachment.image = rendered.image
        let descent = rendered.image.size.height - rendered.baselineFromTop
        attachment.bounds = NSRect(
            x: 0,
            y: -descent,
            width: rendered.image.size.width,
            height: rendered.image.size.height
        )
        return NSAttributedString(attachment: attachment)
    }

    static func reference(
        _ reference: ResearchDocumentTypedLink,
        font: NSFont
    ) -> NSAttributedString {
        let result = NSMutableAttributedString()
        if let icon = referenceIcon(reference, font: font) {
            result.append(icon)
        }
        let label = NSMutableAttributedString(
            string: " \(reference.label)",
            attributes: [
                .font: font,
                .foregroundColor: ResearchDocumentTypedLinkPresentation.nsColor(
                    for: reference.kind
                ),
                ResearchDocumentReferenceTextAttribute.label: reference.label,
            ]
        )
        if let url = reference.url {
            label.addAttribute(
                .link,
                value: url,
                range: NSRange(location: 0, length: label.length)
            )
        }
        result.append(label)
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
        ) else { return nil }
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
        if let url = reference.url {
            result.addAttribute(.link, value: url, range: range)
        }
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
