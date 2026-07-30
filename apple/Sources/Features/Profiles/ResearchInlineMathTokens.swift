import Foundation

enum ResearchInlineMathToken: Equatable {
    case text(String)
    case formula(String)
}

enum ResearchInlineMathTokens {
    private static let expression = try! NSRegularExpression(
        pattern: #"\\\(([\s\S]+?)\\\)"#
    )

    static func parse(_ source: String) -> [ResearchInlineMathToken] {
        let range = NSRange(source.startIndex..., in: source)
        let matches = expression.matches(in: source, range: range)
        guard !matches.isEmpty else { return [.text(source)] }
        var result: [ResearchInlineMathToken] = []
        var cursor = source.startIndex
        for match in matches {
            guard let whole = Range(match.range(at: 0), in: source),
                  let formula = Range(match.range(at: 1), in: source) else {
                continue
            }
            if cursor < whole.lowerBound {
                result.append(.text(String(source[cursor..<whole.lowerBound])))
            }
            result.append(.formula(String(source[formula])))
            cursor = whole.upperBound
        }
        if cursor < source.endIndex {
            result.append(.text(String(source[cursor...])))
        }
        return result.isEmpty ? [.text(source)] : result
    }

    static func formulas(in source: String) -> [String] {
        parse(source).compactMap {
            guard case let .formula(value) = $0 else { return nil }
            return value
        }
    }
}
