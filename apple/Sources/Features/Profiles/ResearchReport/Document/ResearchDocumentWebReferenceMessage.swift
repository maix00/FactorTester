import Foundation

enum ResearchDocumentWebReferenceMessage {
    static let handlerName = "researchReference"

    static func decode(_ body: Any) -> ResearchDocumentTypedLink? {
        guard let payload = body as? [String: Any],
              let href = payload["href"] as? String,
              let url = URL(string: href) else { return nil }
        var reference: ResearchDocumentTypedLink?
        if ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
           ResearchDocumentTypedLinkParser.isSafeWebURL(href) {
            reference = .init(kind: "url", targetRef: href, label: href)
        } else {
            reference = ResearchDocumentTypedLinkParser.reference(from: url)
        }
        guard var reference else { return nil }
        let componentID = (payload["component_id"] as? String)
            .flatMap { $0.isEmpty ? nil : $0 }
        let detailFields = ResearchDocumentReferenceFields.parse(payload["detail_fields"])
        if let label = payload["label"] as? String,
           !label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            reference = .init(
                kind: reference.kind,
                targetRef: reference.targetRef,
                label: String(label.prefix(256)),
                componentID: componentID,
                detailFields: detailFields
            )
        } else if componentID != nil || !detailFields.isEmpty {
            reference = .init(
                kind: reference.kind,
                targetRef: reference.targetRef,
                label: reference.label,
                componentID: componentID,
                detailFields: detailFields
            )
        }
        return reference
    }
}

/// Report navigation emitted by the embedded Web research shell. The native
/// client owns the tab stack, so a report selection opens a native tab instead
/// of replacing the research shell in the current WebView.
enum ResearchDocumentWebNavigationMessage {
    static let handlerName = "researchNavigation"

    private static let allowedPrefixes = [
        "/research?",
        "/research/",
        "/jobs/",
        "/ic-test",
        "/backtest",
        "/reference?",
        "/products/group/",
        "/products/product/",
        "/products/contract/",
        "/products/continuous-contract/",
        "/factors/family/",
        "/factors/factor/",
        "/factors/set/",
        "/factor-series?",
    ]

    static func path(from body: Any) -> String? {
        guard let payload = body as? [String: Any],
              let path = payload["path"] as? String,
              path.hasPrefix("/"),
              !path.hasPrefix("//"),
              allowedPrefixes.contains(where: path.hasPrefix) else { return nil }
        return path
    }
}
