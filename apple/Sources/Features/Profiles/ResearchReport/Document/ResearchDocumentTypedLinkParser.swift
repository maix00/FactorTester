import Foundation

extension ResearchDocumentTypedLinkParser {
    private static let expression = try! NSRegularExpression(pattern: #"""
    (?<![`\\\w])(https?://[^\s<>()\]]+)
    |(?<![`\\\w/])((?:[^\s\[\]()<>/]+/)*[^\s\[\]()<>/]+\.(?:md|markdown|json|csv|py|txt|pdf|png|jpe?g|svg))(?![\w/])
    """#, options: [.allowCommentsAndWhitespace, .caseInsensitive])

    private struct MarkdownLinkMatch {
        let range: NSRange
        let label: String
        let target: String
    }

    private enum Match {
        case markdown(MarkdownLinkMatch)
        case bare(NSTextCheckingResult)

        var range: NSRange {
            switch self {
            case let .markdown(match): return match.range
            case let .bare(match): return match.range
            }
        }
    }

    private static let inlineCodeExpression = try! NSRegularExpression(
        pattern: #"`+[^`\r\n]*`+"#
    )

    static func segments(in text: String) -> [Segment] {
        guard mayContainReference(text) else { return [.text(text)] }
        let range = NSRange(text.startIndex..., in: text)
        let codeRanges = text.contains("`")
            ? inlineCodeExpression.matches(in: text, range: range).map(\.range)
            : []
        var cursor = text.startIndex
        var result: [Segment] = []
        let matches = markdownMatches(in: text).map(Match.markdown)
            + expression.matches(in: text, range: range).map(Match.bare)
        for match in matches.sorted(by: { $0.range.location < $1.range.location }) {
            guard !codeRanges.contains(where: {
                NSIntersectionRange($0, match.range).length > 0
            }) else { continue }
            guard let whole = Range(match.range, in: text),
                  cursor <= whole.lowerBound else { continue }
            if cursor < whole.lowerBound {
                result.append(.text(String(text[cursor..<whole.lowerBound])))
            }
            let parsedReference: ResearchDocumentTypedLink?
            switch match {
            case let .markdown(markdown):
                parsedReference = reference(
                    label: markdown.label,
                    target: markdown.target
                )
            case let .bare(bare):
                parsedReference = reference(bare, in: text)
            }
            guard let parsedReference else { continue }
            result.append(.reference(parsedReference))
            cursor = whole.upperBound
        }
        if cursor < text.endIndex {
            result.append(.text(String(text[cursor...])))
        }
        return result.isEmpty ? [.text(text)] : result
    }

    static func mayContainReference(_ text: String) -> Bool {
        if text.contains("](") { return true }
        let value = text.lowercased()
        if value.contains("http://") || value.contains("https://") {
            return true
        }
        guard value.contains("/") else { return false }
        return [
            ".md", ".markdown", ".json", ".csv", ".py", ".txt",
            ".pdf", ".png", ".jpg", ".jpeg", ".svg",
        ].contains { value.contains($0) }
    }

    private static func reference(
        _ match: NSTextCheckingResult,
        in text: String
    ) -> ResearchDocumentTypedLink? {
        if let target = value(match, group: 1, in: text),
           isSafeWebURL(target) {
            return .init(kind: "url", targetRef: target, label: target)
        }
        let target = value(match, group: 2, in: text)
        guard let target, isSafeRelativeFilePath(target) else { return nil }
        return .init(kind: "file", targetRef: target, label: target)
    }

    private static func reference(
        label: String,
        target: String
    ) -> ResearchDocumentTypedLink? {
        guard let url = URL(string: target) else { return nil }
        if url.scheme?.lowercased() == "factortester",
           let kind = url.host,
           ResearchDocumentReferenceCatalog.contains(kind) {
            return .init(
                kind: kind,
                targetRef: String(url.path.dropFirst()).removingPercentEncoding
                    ?? String(url.path.dropFirst()),
                label: markdownLabel(label)
            )
        }
        if isSafeWebURL(target) {
            return .init(kind: "url", targetRef: target, label: markdownLabel(label))
        }
        guard isSafeRelativeFilePath(target) else { return nil }
        return .init(kind: "file", targetRef: target, label: markdownLabel(label))
    }

    private static func markdownMatches(in text: String) -> [MarkdownLinkMatch] {
        var result: [MarkdownLinkMatch] = []
        var cursor = text.startIndex
        while cursor < text.endIndex {
            guard text[cursor] == "[", !isEscaped(cursor, in: text) else {
                cursor = text.index(after: cursor)
                continue
            }
            guard let labelEnd = matchingDelimiter(
                in: text,
                from: cursor,
                opening: "[",
                closing: "]"
            ) else {
                cursor = text.index(after: cursor)
                continue
            }
            let targetOpening = text.index(after: labelEnd)
            guard targetOpening < text.endIndex, text[targetOpening] == "(",
                  let targetEnd = matchingDelimiter(
                      in: text,
                      from: targetOpening,
                      opening: "(",
                      closing: ")"
                  ) else {
                cursor = text.index(after: cursor)
                continue
            }
            let targetStart = text.index(after: targetOpening)
            guard targetStart < targetEnd else {
                cursor = text.index(after: targetEnd)
                continue
            }
            let range = NSRange(
                cursor..<text.index(after: targetEnd),
                in: text
            )
            result.append(.init(
                range: range,
                label: String(text[text.index(after: cursor)..<labelEnd]),
                target: String(text[targetStart..<targetEnd])
            ))
            cursor = text.index(after: targetEnd)
        }
        return result
    }

    private static func matchingDelimiter(
        in text: String,
        from opening: String.Index,
        opening open: Character,
        closing close: Character
    ) -> String.Index? {
        var depth = 0
        var cursor = opening
        while cursor < text.endIndex {
            if !isEscaped(cursor, in: text) {
                if text[cursor] == open {
                    depth += 1
                } else if text[cursor] == close {
                    depth -= 1
                    if depth == 0 { return cursor }
                }
            }
            cursor = text.index(after: cursor)
        }
        return nil
    }

    private static func isEscaped(
        _ index: String.Index,
        in text: String
    ) -> Bool {
        var cursor = index
        var slashes = 0
        while cursor > text.startIndex {
            cursor = text.index(before: cursor)
            guard text[cursor] == "\\" else { break }
            slashes += 1
        }
        return slashes % 2 == 1
    }

    private static func markdownLabel(_ value: String) -> String {
        value.replacingOccurrences(
            of: #"\\([\[\]\\])"#,
            with: "$1",
            options: .regularExpression
        )
    }

    private static func value(
        _ match: NSTextCheckingResult,
        group: Int,
        in text: String
    ) -> String? {
        guard match.range(at: group).location != NSNotFound,
              let range = Range(match.range(at: group), in: text) else {
            return nil
        }
        return String(text[range])
    }
}
