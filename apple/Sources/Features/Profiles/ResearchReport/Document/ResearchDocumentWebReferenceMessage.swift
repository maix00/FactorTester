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
