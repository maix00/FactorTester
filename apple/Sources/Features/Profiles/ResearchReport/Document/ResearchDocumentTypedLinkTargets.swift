import Foundation

extension ResearchDocumentTypedLinkParser {
    static func isSafeRelativeFilePath(_ value: String) -> Bool {
        let decoded = value.removingPercentEncoding ?? value
        guard !decoded.isEmpty,
              decoded.utf8.count <= 1_024,
              !decoded.hasPrefix("/"),
              !decoded.hasPrefix("~"),
              !decoded.contains("\\") else {
            return false
        }
        let components = decoded.split(
            separator: "/",
            omittingEmptySubsequences: false
        )
        return !components.isEmpty && components.allSatisfy {
            !$0.isEmpty && $0 != "." && $0 != ".."
        }
    }

    static func isSafeWebURL(_ value: String) -> Bool {
        guard value.utf8.count <= 4_096,
              let url = URL(string: value),
              ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              url.host?.isEmpty == false,
              url.user == nil,
              url.password == nil else {
            return false
        }
        return true
    }

    static func reference(from url: URL) -> ResearchDocumentTypedLink? {
        let path = URLComponents(
            url: url,
            resolvingAgainstBaseURL: false
        )?.percentEncodedPath ?? ""
        guard url.scheme == "factortester",
              let kind = url.host,
              ResearchDocumentReferenceCatalog.contains(kind),
              !path.isEmpty,
              path.first == "/",
              let target = String(
                  path.dropFirst()
              ).removingPercentEncoding,
              !target.isEmpty else {
            return nil
        }
        return .init(kind: kind, targetRef: target, label: target)
    }

    static func reference(
        from url: URL,
        preservingLabelIn source: String
    ) -> ResearchDocumentTypedLink? {
        guard let parsed = reference(from: url) else { return nil }
        return segments(in: source).compactMap { segment in
            guard case let .reference(reference) = segment,
                  reference.kind == parsed.kind,
                  reference.targetRef == parsed.targetRef else {
                return nil
            }
            return reference
        }.first ?? parsed
    }
}
