import SwiftUI

private struct ResearchDocumentReferenceActionKey: EnvironmentKey {
    static let defaultValue: (ResearchDocumentTypedLink) -> Void = { _ in }
}

extension EnvironmentValues {
    var researchDocumentReferenceAction: (ResearchDocumentTypedLink) -> Void {
        get { self[ResearchDocumentReferenceActionKey.self] }
        set { self[ResearchDocumentReferenceActionKey.self] = newValue }
    }
}

enum ResearchDocumentReferenceRouter {
    static func jobID(from reference: ResearchDocumentTypedLink) -> String? {
        guard reference.kind == "job" else { return nil }
        for prefix in ["research-job:", "job:"] where reference.targetRef.hasPrefix(prefix) {
            let value = String(reference.targetRef.dropFirst(prefix.count))
            if isSafeIdentifier(value) { return value }
        }
        return nil
    }

    static func cycleObjectHref(
        for reference: ResearchDocumentTypedLink,
        steps: [ResearchTransitionStep]
    ) -> String? {
        let objectKind = reference.kind == "trial_plan"
            ? "trial_plan" : reference.kind
        return steps.reversed().lazy.compactMap { step in
            guard step.allRefs.contains(reference.targetRef) else { return nil }
            return step.objectHref(
                kind: objectKind,
                targetRef: reference.targetRef
            )
        }.first
    }

    private static func isSafeIdentifier(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 128 else { return false }
        return value.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0) || "._-".unicodeScalars.contains($0)
        }
    }
}
