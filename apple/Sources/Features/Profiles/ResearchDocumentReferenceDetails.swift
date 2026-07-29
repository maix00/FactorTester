import Foundation

struct ResearchDocumentReferenceSection: Identifiable {
    let title: String
    let fields: [ResearchDocumentReferenceField]
    var id: String { title }
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
            ] + (binding?.detailFields ?? []))
        )]
        let object = payload ?? evidence?.envelope
        switch reference.kind {
        case "evidence":
            values += ResearchDocumentEvidenceSections.make(
                payload: object,
                detail: evidence
            )
        case "obligation":
            values += ResearchDocumentGraphObjectSections.obligation(object)
        case "claim":
            values += ResearchDocumentGraphObjectSections.claim(object)
        case "trial_plan":
            values += ResearchDocumentGraphObjectSections.trialPlan(object)
        case "run", "run_spec":
            values += ResearchDocumentGraphObjectSections.run(object)
        case "delta":
            values += ResearchDocumentGraphObjectSections.delta(object)
        default:
            values += ResearchDocumentGraphObjectSections.generic(object)
        }
        return values.filter { !$0.fields.isEmpty }
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
        _ fields: [ResearchDocumentReferenceField]
    ) -> ResearchDocumentReferenceSection {
        .init(title: L10n.text(title), fields: unique(fields))
    }
}
