#if os(macOS)
import AppKit

final class ResearchInlineCodeLayoutManager: NSLayoutManager {
    static let attribute = NSAttributedString.Key(
        "com.gtht.factortester.inline-code"
    )
    static let horizontalBackgroundOutset: CGFloat = 0
    static let verticalBackgroundOutset: CGFloat = 0.5
    static let cornerRadius: CGFloat = 6

    override func drawBackground(
        forGlyphRange glyphsToShow: NSRange,
        at origin: NSPoint
    ) {
        super.drawBackground(forGlyphRange: glyphsToShow, at: origin)
        guard let textStorage,
              let container = textContainers.first else {
            return
        }
        let characters = characterRange(
            forGlyphRange: glyphsToShow,
            actualGlyphRange: nil
        )
        textStorage.enumerateAttribute(
            Self.attribute,
            in: characters
        ) { value, characterRange, _ in
            guard value != nil else { return }
            for background in self.backgroundRects(
                forCharacterRange: characterRange,
                visibleGlyphRange: glyphsToShow,
                in: container,
                at: origin
            ) {
                NSColor.labelColor.withAlphaComponent(0.10).setFill()
                NSBezierPath(
                    roundedRect: background,
                    xRadius: Self.cornerRadius,
                    yRadius: Self.cornerRadius
                ).fill()
            }
        }
    }

    func backgroundRects(
        forCharacterRange characterRange: NSRange,
        visibleGlyphRange: NSRange,
        in container: NSTextContainer,
        at origin: NSPoint = .zero
    ) -> [NSRect] {
        guard let textStorage,
              characterRange.length > 0,
              characterRange.location < textStorage.length else {
            return []
        }
        let codeGlyphs = glyphRange(
            forCharacterRange: characterRange,
            actualCharacterRange: nil
        )
        let visibleCodeGlyphs = NSIntersectionRange(
            codeGlyphs,
            visibleGlyphRange
        )
        guard visibleCodeGlyphs.length > 0 else { return [] }
        let font = textStorage.attribute(
            .font,
            at: characterRange.location,
            effectiveRange: nil
        ) as? NSFont ?? NSFont.monospacedSystemFont(
            ofSize: NSFont.systemFontSize,
            weight: .regular
        )
        var result: [NSRect] = []
        enumerateLineFragments(
            forGlyphRange: visibleCodeGlyphs
        ) { lineRect, _, _, lineGlyphs, _ in
            let fragmentGlyphs = NSIntersectionRange(
                visibleCodeGlyphs,
                lineGlyphs
            )
            guard fragmentGlyphs.length > 0 else { return }
            let bounds = self.boundingRect(
                forGlyphRange: fragmentGlyphs,
                in: container
            )
            guard bounds.width > 0.5 else { return }

            // `enumerateEnclosingRects` includes paragraph line spacing in a
            // non-final line fragment. Centering the code background inside
            // that rectangle therefore leaves visibly more fill below the
            // baseline whenever the paragraph wraps. Anchor it to the actual
            // glyph baseline instead; paragraph spacing must never contribute
            // to the inline token's background geometry.
            let glyphLocation = self.location(
                forGlyphAt: fragmentGlyphs.location
            )
            let baselineY = lineRect.minY + glyphLocation.y
            let compact = NSRect(
                x: bounds.minX,
                y: baselineY - font.ascender,
                width: bounds.width,
                height: font.ascender - font.descender
            )
            result.append(
                compact
                    .offsetBy(dx: origin.x, dy: origin.y)
                    .insetBy(
                        dx: -Self.horizontalBackgroundOutset,
                        dy: -Self.verticalBackgroundOutset
                    )
            )
        }
        return result
    }
}
#endif
