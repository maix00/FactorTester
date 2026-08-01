#if os(macOS)
import AppKit

enum ResearchInlineCodeAttributedString {
    static func make(
        _ source: String,
        font: NSFont
    ) -> NSAttributedString {
        let value = ResearchDocumentInlineTextStyle.markdown(source)
        let rendered = NSMutableAttributedString(
            attributedString: NSAttributedString(value)
        )
        rendered.addAttribute(
            .font,
            value: font,
            range: NSRange(location: 0, length: rendered.length)
        )
        for range in codeRanges(in: value).reversed() {
            rendered.replaceCharacters(
                in: range,
                with: paddedCode(
                    rendered.attributedSubstring(from: range),
                    range: range,
                    in: rendered,
                    font: font
                )
            )
        }
        return rendered
    }

    private static func codeRanges(in value: AttributedString) -> [NSRange] {
        let characters = value.characters
        return value.runs.compactMap { run in
            guard run.inlinePresentationIntent?.contains(.code) == true else {
                return nil
            }
            let start = characters.distance(
                from: characters.startIndex,
                to: run.range.lowerBound
            )
            let length = characters.distance(
                from: run.range.lowerBound,
                to: run.range.upperBound
            )
            return NSRange(location: start, length: length)
        }
    }

    private static func paddedCode(
        _ value: NSAttributedString,
        range: NSRange,
        in source: NSAttributedString,
        font: NSFont
    ) -> NSAttributedString {
        let result = NSMutableAttributedString()
        if needsOuterSpacing(before: range.location, in: source.string) {
            result.append(outerSpacing(font: font))
        }
        result.append(innerPadding(font: font))
        result.append(styledCode(value, font: font))
        result.append(innerPadding(font: font))
        if needsOuterSpacing(
            before: NSMaxRange(range),
            in: source.string,
            lookingBackward: false
        ) {
            result.append(outerSpacing(font: font))
        }
        return result
    }

    private static func styledCode(
        _ value: NSAttributedString,
        font: NSFont
    ) -> NSAttributedString {
        let code = NSMutableAttributedString(attributedString: value)
        let range = NSRange(location: 0, length: code.length)
        code.removeAttribute(.backgroundColor, range: range)
        code.addAttributes(codeAttributes(font: font), range: range)
        return code
    }

    private static func innerPadding(font: NSFont) -> NSAttributedString {
        NSAttributedString(
            string: "\u{00a0}",
            attributes: codeAttributes(font: font)
        )
    }

    private static func outerSpacing(font: NSFont) -> NSAttributedString {
        NSAttributedString(string: "\u{200a}", attributes: [.font: font])
    }

    private static func needsOuterSpacing(
        before location: Int,
        in value: String,
        lookingBackward: Bool = true
    ) -> Bool {
        let text = value as NSString
        let index = lookingBackward ? location - 1 : location
        guard index >= 0, index < text.length else { return false }
        let scalar = UnicodeScalar(text.character(at: index))
        return scalar.map {
            !CharacterSet.whitespacesAndNewlines.contains($0)
        } ?? true
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
