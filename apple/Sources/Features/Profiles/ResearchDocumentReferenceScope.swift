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
        return Self.spacingReferenceAssignments(resolved)
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

    private static func spacingReferenceAssignments(
        _ segments: [ResearchDocumentTypedLinkParser.Segment]
    ) -> [ResearchDocumentTypedLinkParser.Segment] {
        var result: [ResearchDocumentTypedLinkParser.Segment] = []
        for segment in segments {
            if case let .text(value) = segment,
               case .reference? = result.last,
               let match = value.range(
                   of: #"^\s*=\s*"#,
                   options: .regularExpression
               ) {
                result.append(.text(
                    " = " + value[match.upperBound...]
                ))
            } else {
                result.append(segment)
            }
        }
        return result
    }
}
