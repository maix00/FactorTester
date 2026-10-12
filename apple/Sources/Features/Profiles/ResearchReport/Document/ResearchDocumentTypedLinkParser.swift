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

    static func isSafeWebURL(_ rawValue: String) -> Bool {
        guard rawValue == rawValue.trimmingCharacters(in: .whitespacesAndNewlines),
              !rawValue.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains),
              !rawValue.unicodeScalars.contains(where: CharacterSet.whitespacesAndNewlines.contains),
              let components = URLComponents(string: rawValue),
              let scheme = components.scheme?.lowercased(),
              ["http", "https"].contains(scheme),
              let host = components.host,
              !host.isEmpty,
              components.user == nil,
              components.password == nil,
              components.port.map({ (1...65_535).contains($0) }) ?? true else {
            return false
        }
        return true
    }

    static func isSafeRelativeFilePath(_ rawValue: String) -> Bool {
        guard !rawValue.isEmpty,
              rawValue.utf8.count <= 2_048,
              rawValue == rawValue.trimmingCharacters(in: .whitespacesAndNewlines),
              !rawValue.hasPrefix("/"),
              !rawValue.contains("\\"),
              !rawValue.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains),
              rawValue.range(of: #"^[A-Za-z]:"#, options: .regularExpression) == nil else {
            return false
        }

        var candidate = rawValue
        for _ in 0..<8 {
            guard !candidate.hasPrefix("/"),
                  !candidate.contains("\\"),
                  !candidate.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains) else {
                return false
            }
            let components = candidate.split(separator: "/", omittingEmptySubsequences: false)
            guard !components.isEmpty,
                  components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }),
                  let decoded = candidate.removingPercentEncoding else {
                return false
            }
            if decoded == candidate { return true }
            candidate = decoded
        }
        return false
    }

    static func reference(from url: URL) -> ResearchDocumentTypedLink? {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              components.scheme?.lowercased() == "factortester",
              components.user == nil,
              components.password == nil,
              components.port == nil,
              components.query == nil,
              components.fragment == nil,
              let rawKind = components.host,
              components.percentEncodedPath.hasPrefix("/"),
              let target = String(components.percentEncodedPath.dropFirst())
                  .removingPercentEncoding,
              !target.isEmpty else {
            return nil
        }
        return makeReference(kind: rawKind, target: target, label: target)
    }

    static func reference(
        from url: URL,
        preservingLabelIn text: String
    ) -> ResearchDocumentTypedLink? {
        guard let parsed = reference(from: url) else { return nil }
        return segments(in: text).compactMap { segment -> ResearchDocumentTypedLink? in
            guard case let .reference(candidate) = segment,
                  candidate.kind == parsed.kind,
                  candidate.targetRef == parsed.targetRef else { return nil }
            return candidate
        }.first ?? parsed
    }

    private static func reference(
        _ match: NSTextCheckingResult,
        in text: String
    ) -> ResearchDocumentTypedLink? {
        if let target = value(match, group: 1, in: text),
           isSafeWebURL(target) {
            return makeReference(kind: "url", target: target, label: target)
        }
        let target = value(match, group: 2, in: text)
        guard let target, isSafeRelativeFilePath(target) else { return nil }
        return makeReference(kind: "file", target: target, label: target)
    }

    private static func reference(
        label: String,
        target: String
    ) -> ResearchDocumentTypedLink? {
        guard let url = URL(string: target) else { return nil }
        if url.scheme?.lowercased() == "factortester" {
            guard var parsed = reference(from: url) else { return nil }
            parsed = .init(
                kind: parsed.kind,
                targetRef: parsed.targetRef,
                label: markdownLabel(label)
            )
            return parsed
        }
        if isSafeWebURL(target) {
            return makeReference(
                kind: "url", target: target, label: markdownLabel(label)
            )
        }
        guard isSafeRelativeFilePath(target) else { return nil }
        return makeReference(
            kind: "file", target: target, label: markdownLabel(label)
        )
    }

    private static func makeReference(
        kind rawKind: String,
        target: String,
        label: String
    ) -> ResearchDocumentTypedLink? {
        let kind = ResearchDocumentReferenceCatalog.canonicalKind(rawKind)
        guard ResearchDocumentReferenceCatalog.contains(kind),
              !target.isEmpty,
              !target.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains) else {
            return nil
        }
        if kind == "url" && !isSafeWebURL(target) { return nil }
        if kind == "file" && !isSafeFileReference(target) { return nil }
        return .init(kind: kind, targetRef: target, label: label)
    }

    private static func isSafeFileReference(_ target: String) -> Bool {
        if isSafeRelativeFilePath(target) { return true }
        guard let components = URLComponents(string: target),
              components.scheme?.lowercased() == "factortester-local",
              let host = components.host,
              !host.isEmpty,
              host.unicodeScalars.allSatisfy({
                  CharacterSet.alphanumerics.contains($0) || "._-".unicodeScalars.contains($0)
              }),
              components.user == nil,
              components.password == nil,
              components.port == nil,
              components.query == nil,
              components.fragment == nil else {
            return false
        }
        if components.percentEncodedPath.isEmpty { return true }
        guard components.percentEncodedPath.hasPrefix("/"),
              let path = String(components.percentEncodedPath.dropFirst())
                  .removingPercentEncoding else { return false }
        return isSafeRelativeFilePath(path)
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
