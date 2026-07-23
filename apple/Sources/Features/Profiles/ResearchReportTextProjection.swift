import Foundation

struct ResearchReportTextComponent: Equatable {
    enum Kind: Equatable {
        case prose
        case math
    }

    let kind: Kind
    let text: String
}

enum ResearchReportTextProjection {
    static func mathJaxSource(_ value: String) -> String {
        // Historical reports used `$F` / `$Rev` as compact variable markup.
        // Normalize only identifier-shaped tokens; currency such as `$100`
        // remains ordinary prose. Proper paired `$...$` is left to MathJax.
        guard let expression = try? NSRegularExpression(
            pattern: #"\$([A-Za-z][A-Za-z0-9_]*)\b(?!\$)"#
        ) else { return value }
        return expression.stringByReplacingMatches(
            in: value,
            range: NSRange(value.startIndex..., in: value),
            withTemplate: #"\\($1\\)"#
        )
    }

    static func containsMath(_ value: String) -> Bool {
        let normalized = mathJaxSource(value)
        if normalized.range(of: #"\\\(.+?\\\)"#, options: .regularExpression)
            != nil {
            return true
        }
        return normalized.range(
            of: #"\$[^$\n]+\$"#,
            options: .regularExpression
        ) != nil
    }

    static func components(_ value: String) -> [ResearchReportTextComponent] {
        let pattern = #"\\\((.+?)\\\)"#
        guard let expression = try? NSRegularExpression(pattern: pattern)
        else {
            return [.init(kind: .prose, text: value)]
        }
        let range = NSRange(value.startIndex..., in: value)
        let matches = expression.matches(in: value, range: range)
        guard !matches.isEmpty else {
            return [.init(kind: .prose, text: value)]
        }
        var result: [ResearchReportTextComponent] = []
        var cursor = value.startIndex
        for match in matches {
            guard let whole = Range(match.range(at: 0), in: value),
                  let formula = Range(match.range(at: 1), in: value)
            else { continue }
            appendProse(String(value[cursor..<whole.lowerBound]), to: &result)
            result.append(.init(kind: .math, text: String(value[formula])))
            cursor = whole.upperBound
        }
        appendProse(String(value[cursor...]), to: &result)
        return result.isEmpty ? [.init(kind: .prose, text: value)] : result
    }

    private static func appendProse(
        _ value: String,
        to result: inout [ResearchReportTextComponent]
    ) {
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.isEmpty {
            result.append(.init(kind: .prose, text: text))
        }
    }
}
