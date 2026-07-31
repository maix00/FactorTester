import Foundation

struct ResearchDocumentJobRoute: Equatable {
    let jobID: String
    let port: Int
}

enum ResearchDocumentReferenceBindingResolver {
    static func binding(
        for reference: ResearchDocumentTypedLink,
        in bindings: [ResearchDocumentBinding]
    ) -> ResearchDocumentBinding? {
        guard let componentID = reference.componentID,
              !componentID.isEmpty else { return nil }
        if let direct = bindings.first(where: {
            $0.componentID == componentID
                && $0.kind == reference.kind
                && $0.targetRef == reference.targetRef
        }) { return direct }
        for parent in bindings where parent.componentID == componentID {
            if let related = parent.relatedReferences.first(where: {
                $0.reference.kind == reference.kind
                    && $0.reference.targetRef == reference.targetRef
            }) {
                return ResearchDocumentBinding(
                    id: "\(parent.id)-\(related.id)",
                    componentID: componentID,
                    kind: reference.kind,
                    targetRef: reference.targetRef,
                    label: related.reference.label,
                    detailFields: related.detailFields,
                    relatedReferences: []
                )
            }
        }
        return nil
    }

    static func profileID(
        for reference: ResearchDocumentTypedLink,
        binding: ResearchDocumentBinding?
    ) -> String? {
        guard let binding,
              binding.kind == reference.kind,
              binding.targetRef == reference.targetRef else { return nil }
        return ResearchDocumentReferenceRouter.profileID(from: reference)
    }

    static func jobRoute(
        for reference: ResearchDocumentTypedLink,
        binding: ResearchDocumentBinding?
    ) -> ResearchDocumentJobRoute? {
        guard let jobID = ResearchDocumentReferenceRouter.jobID(from: reference),
              let binding,
              binding.kind == reference.kind,
              binding.targetRef == reference.targetRef,
              let portValue = binding.detailFields.first(where: {
                  $0.name == "port"
              })?.value,
              let port = Int(portValue),
              (1...65_535).contains(port) else { return nil }
        return .init(jobID: jobID, port: port)
    }
}
