import Foundation

struct ResearchDocumentReferenceScope {
    let componentID: String
    let bindings: [ResearchDocumentBinding]

    func trusted(
        _ reference: ResearchDocumentTypedLink
    ) -> ResearchDocumentTypedLink? {
        if Self.isExternal(reference) {
            return reference.located(in: componentID)
        }
        let located = reference.located(in: componentID)
        guard ResearchDocumentReferenceBindingResolver.binding(
            for: located,
            in: bindings
        ) != nil else {
            return nil
        }
        return located
    }

    func presentationSegments(
        in text: String
    ) -> [ResearchDocumentTypedLinkParser.Segment] {
        let resolved = ResearchDocumentTypedLinkParser.segments(in: text).map { segment in
            guard case let .reference(reference) = segment,
                  trusted(reference) == nil else {
                return segment
            }
            return .text(reference.label)
        }
        return resolved.map { segment in
            guard case let .text(value) = segment else { return segment }
            return .text(Self.spacingStandaloneEquals(in: value))
        }
    }

    var webTrustedReferenceKeys: [String] {
        guard !componentID.isEmpty else { return [] }
        return bindings.compactMap { binding in
            guard binding.componentID == componentID,
                  ResearchDocumentReferenceCatalog.contains(binding.kind),
                  !Self.isExternalKind(binding.kind) else {
                return nil
            }
            return Self.webKey(
                kind: binding.kind,
                targetRef: binding.targetRef
            )
        }
    }

    static func webKey(kind: String, targetRef: String) -> String {
        "\(kind)\u{1f}\(targetRef)"
    }

    private static func isExternal(
        _ reference: ResearchDocumentTypedLink
    ) -> Bool {
        isExternalKind(reference.kind)
    }

    private static func isExternalKind(_ kind: String) -> Bool {
        kind == "url" || kind == "file"
    }

    private static func spacingStandaloneEquals(in value: String) -> String {
        guard value.contains("=") else { return value }
        let expression = try! NSRegularExpression(
            pattern: #"`+[^`\r\n]*`+"#
        )
        let range = NSRange(value.startIndex..., in: value)
        var cursor = value.startIndex
        var result = ""
        for match in expression.matches(in: value, range: range) {
            guard let codeRange = Range(match.range, in: value) else { continue }
            result += spacingEquals(String(value[cursor..<codeRange.lowerBound]))
            result += value[codeRange]
            cursor = codeRange.upperBound
        }
        result += spacingEquals(String(value[cursor...]))
        return result
    }

    private static func spacingEquals(_ value: String) -> String {
        value.replacingOccurrences(
            of: #"(?<![<>=!])\s*=\s*(?![=>])"#,
            with: " = ",
            options: .regularExpression
        )
    }
}
