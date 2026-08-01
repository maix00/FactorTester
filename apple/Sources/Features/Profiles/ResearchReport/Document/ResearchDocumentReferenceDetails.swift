import Foundation

struct ResearchDocumentReferenceSection: Identifiable {
    let title: String
    let fields: [ResearchDocumentReferenceField]
    let links: [ResearchDocumentRelatedReference]
    var id: String { title }

    init(
        title: String,
        fields: [ResearchDocumentReferenceField],
        links: [ResearchDocumentRelatedReference] = []
    ) {
        self.title = title
        self.fields = fields
        self.links = links
    }
}

enum ResearchDocumentReferenceDetails {
    static func sections(
        reference: ResearchDocumentTypedLink,
        binding: ResearchDocumentBinding?,
        payload: ResearchAuditObjectPayload?,
        evidence: ResearchEvidenceDetailPayload?
    ) -> [ResearchDocumentReferenceSection] {
        var values = [ResearchDocumentReferenceSection(
            title: L10n.text("对象说明"),
            fields: DetailFields.unique([
                DetailFields.field(
                    "类型",
                    ResearchDocumentTypedLinkPresentation.title(
                        for: reference.kind
                    )
                ),
                DetailFields.field("名称", reference.label),
                DetailFields.field("对象引用", reference.targetRef),
            ] + (binding?.detailFields ?? [])),
            links: binding?.relatedReferences ?? []
        )]
        let object = payload ?? evidence?.envelope
        switch reference.kind {
        case "evidence":
            values += ResearchDocumentEvidenceSections.make(
                payload: object,
                detail: evidence
            )
        case "obligation":
            values += ResearchDocumentGraphObjectSections.obligation(
                object, related: binding?.relatedReferences ?? []
            )
        case "claim":
            values += ResearchDocumentGraphObjectSections.claim(
                object, related: binding?.relatedReferences ?? []
            )
        case "trial_plan":
            values += ResearchDocumentGraphObjectSections.trialPlan(object)
        case "run", "run_spec":
            values += ResearchDocumentGraphObjectSections.run(object)
        case "delta":
            values += ResearchDocumentGraphObjectSections.delta(object)
        default:
            values += ResearchDocumentGraphObjectSections.generic(object)
        }
        return values.filter { !$0.fields.isEmpty || !$0.links.isEmpty }
    }
}

enum DetailFields {
    static func field(
        _ name: String,
        _ value: String?
    ) -> ResearchDocumentReferenceField {
        .init(name: L10n.text(name), value: value ?? "")
    }

    static func values(
        _ name: String,
        _ values: [String]?
    ) -> ResearchDocumentReferenceField {
        field(name, values?.joined(separator: "、"))
    }

    static func unique(
        _ fields: [ResearchDocumentReferenceField]
    ) -> [ResearchDocumentReferenceField] {
        var names = Set<String>()
        return fields.filter {
            !$0.value.isEmpty && names.insert($0.name).inserted
        }
    }

    static func section(
        _ title: String,
        _ fields: [ResearchDocumentReferenceField],
        links: [ResearchDocumentRelatedReference] = []
    ) -> ResearchDocumentReferenceSection {
        .init(title: L10n.text(title), fields: unique(fields), links: links)
    }
}
