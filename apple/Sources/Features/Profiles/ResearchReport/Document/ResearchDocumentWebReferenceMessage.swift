import Foundation

enum ResearchDocumentWebReferenceMessage {
    static let handlerName = "researchReference"

    static func decode(_ body: Any) -> ResearchDocumentTypedLink? {
        guard let payload = body as? [String: Any],
              let href = payload["href"] as? String,
              let url = URL(string: href),
              var reference = ResearchDocumentTypedLinkParser.reference(from: url)
        else { return nil }
        if let label = payload["label"] as? String,
           !label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            reference = .init(
                kind: reference.kind,
                targetRef: reference.targetRef,
                label: String(label.prefix(256))
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

    static func path(from body: Any) -> String? {
        guard let payload = body as? [String: Any],
              let path = payload["path"] as? String,
              path.hasPrefix("/research/") else { return nil }
        return path
    }
}
