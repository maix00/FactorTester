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
        case "trial_plan":
            values += ResearchDocumentFrozenObjectSections.trialPlan(object)
        case "run", "run_spec":
            values += ResearchDocumentFrozenObjectSections.run(object)
        default:
            values += ResearchDocumentFrozenObjectSections.generic(object)
        }
        return values.filter { !$0.fields.isEmpty || !$0.links.isEmpty }
    }
}

enum ResearchDocumentFrozenObjectSections {
    static func trialPlan(
        _ value: ResearchAuditObjectPayload?
    ) -> [ResearchDocumentReferenceSection] {
        guard let value else { return [] }
        let outcomes = (value.outcomes?.primary ?? [])
            + (value.outcomes?.secondary ?? [])
        let samples = value.sampleRoles?.map {
            "\($0.sampleRef)（\($0.role)）"
        }
        return [DetailFields.section("试验设计", [
            DetailFields.field("摘要", value.summaryZH),
            DetailFields.field("假设", value.hypothesisRef),
            DetailFields.field("试验族", value.trialFamily),
            DetailFields.field("协议", value.protocolRef),
            DetailFields.values("样本角色", samples),
            DetailFields.values("检验结果", outcomes),
            DetailFields.field("停止条件", value.stopCondition),
        ])]
    }

    static func run(
        _ value: ResearchAuditObjectPayload?
    ) -> [ResearchDocumentReferenceSection] {
        guard let value else { return [] }
        return [DetailFields.section("测试配置", [
            DetailFields.field("摘要", value.summaryZH),
            DetailFields.field("运行 ID", value.runID),
            DetailFields.field("配置 ID", value.configurationID),
            DetailFields.field(
                "配置版本", value.configurationRevision.map(String.init)
            ),
            DetailFields.field("试验阶段", value.trialStage),
            DetailFields.field("试验角色", value.trialRole),
            DetailFields.field("样本", value.sampleRef),
            DetailFields.field("样本开始", value.sampleStart),
            DetailFields.field("样本结束", value.sampleEnd),
            DetailFields.field("RunSpec 哈希", value.runSpecHash),
        ])]
    }

    static func generic(
        _ value: ResearchAuditObjectPayload?
    ) -> [ResearchDocumentReferenceSection] {
        guard let value else { return [] }
        return [DetailFields.section("对象详情", [
            DetailFields.field("对象类型", value.objectKind),
            DetailFields.field("对象 ID", value.objectID),
            DetailFields.field("状态", value.status),
            DetailFields.field("摘要", value.summaryZH),
        ])]
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
