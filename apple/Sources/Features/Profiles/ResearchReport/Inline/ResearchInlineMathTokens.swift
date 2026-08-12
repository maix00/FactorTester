import Foundation

enum ResearchInlineMathToken: Equatable {
    case text(String)
    case formula(String)
}

enum ResearchInlineMathTokens {
    private final class TokenBox: NSObject {
        let value: [ResearchInlineMathToken]

        init(_ value: [ResearchInlineMathToken]) {
            self.value = value
        }
    }

    private static let expression = try! NSRegularExpression(
        pattern: #"\\\(([\s\S]+?)\\\)"#
    )
    private static let cache: NSCache<NSString, TokenBox> = {
        let cache = NSCache<NSString, TokenBox>()
        cache.countLimit = 512
        cache.totalCostLimit = 2 * 1_024 * 1_024
        return cache
    }()

    static func parse(_ source: String) -> [ResearchInlineMathToken] {
        let key = source as NSString
        if let cached = cache.object(forKey: key) { return cached.value }
        let parsed = parseUncached(source)
        cache.setObject(TokenBox(parsed), forKey: key, cost: source.utf8.count)
        return parsed
    }

    private static func parseUncached(
        _ source: String
    ) -> [ResearchInlineMathToken] {
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
