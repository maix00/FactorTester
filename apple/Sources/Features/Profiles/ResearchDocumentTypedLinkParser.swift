import Foundation

extension ResearchDocumentTypedLinkParser {
    private static let expression = try! NSRegularExpression(pattern: #"""
    (?<!\\)\[((?:\\[\[\]\\]|[^\[\]\\\r\n]){1,512})\]\(factortester://([a-z_]+)/([^()\s]+)\)
    |(?<!\\)\[((?:\\[\[\]\\]|[^\[\]\\\r\n]){1,512})\]\((https?://[^\s()]+)\)
    |(?<!\\)\[((?:\\[\[\]\\]|[^\[\]\\\r\n]){1,512})\]\(((?:[^\s\[\]()<>/]+/)*[^\s\[\]()<>/]+\.(?:md|markdown|json|csv|py|txt|pdf|png|jpe?g|svg))\)
    |(?<![`\\\w])(https?://[^\s<>()\]]+)
    |(?<![`\\\w/])((?:[^\s\[\]()<>/]+/)*[^\s\[\]()<>/]+\.(?:md|markdown|json|csv|py|txt|pdf|png|jpe?g|svg))(?![\w/])
    """#, options: [.allowCommentsAndWhitespace, .caseInsensitive])

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
        for match in expression.matches(in: text, range: range) {
            guard !codeRanges.contains(where: {
                NSIntersectionRange($0, match.range).length > 0
            }) else { continue }
            guard let whole = Range(match.range, in: text),
                  cursor <= whole.lowerBound else { continue }
            if cursor < whole.lowerBound {
                result.append(.text(String(text[cursor..<whole.lowerBound])))
            }
            guard let reference = reference(match, in: text) else { continue }
            result.append(.reference(reference))
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
        if let label = value(match, group: 1, in: text),
           let kind = value(match, group: 2, in: text),
           let target = value(match, group: 3, in: text),
           ResearchDocumentReferenceCatalog.contains(kind) {
            return .init(
                kind: kind,
                targetRef: target.removingPercentEncoding ?? target,
                label: markdownLabel(label)
            )
        }
        if let label = value(match, group: 4, in: text),
           let target = value(match, group: 5, in: text),
           isSafeWebURL(target) {
            return .init(
                kind: "url", targetRef: target,
                label: markdownLabel(label)
            )
        }
        if let target = value(match, group: 8, in: text),
           isSafeWebURL(target) {
            return .init(kind: "url", targetRef: target, label: target)
        }
        let label = value(match, group: 6, in: text)
        let target = value(match, group: 7, in: text)
            ?? value(match, group: 9, in: text)
        guard let target, isSafeRelativeFilePath(target) else { return nil }
        return .init(
            kind: "file",
            targetRef: target,
            label: label.map(markdownLabel) ?? target
        )
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
