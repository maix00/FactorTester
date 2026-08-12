import Foundation

enum ResearchDocumentGraphObjectSections {
    static func obligation(
        _ value: ResearchAuditObjectPayload?,
        related: [ResearchDocumentRelatedReference] = []
    ) -> [ResearchDocumentReferenceSection] {
        guard let value else { return [] }
        return [
            DetailFields.section("研究含义", [
                DetailFields.field("短中文标题", value.titleZH),
                DetailFields.field("待回答问题", value.epistemicQuestion),
                DetailFields.field("义务类型", value.obligationKind),
                DetailFields.field("状态", value.status),
                DetailFields.field("重要性", value.materiality),
            ]),
            DetailFields.section(
                "完成条件",
                legacyFields(
                    related: related,
                    values: [
                        ("要求", value.requirementRefs),
                        ("关联主张", value.claimIDs),
                    ]
                ) + json(value.dischargeCriterion, prefix: "完成标准"),
                links: related.filter {
                    ["要求", "关联主张"].contains($0.relation)
                }
            ),
            DetailFields.section("适用范围", json(value.scope, prefix: "范围")),
            DetailFields.section("来源与审计", [
                DetailFields.field("创建记录", value.createdEventRef),
            ]),
        ]
    }

    static func claim(
        _ value: ResearchAuditObjectPayload?,
        related: [ResearchDocumentRelatedReference] = []
    ) -> [ResearchDocumentReferenceSection] {
        guard let value else { return [] }
        return [
            DetailFields.section("研究含义", [
                DetailFields.field("研究主张", value.claimRef),
                DetailFields.field("主张类型", value.claimType),
                DetailFields.field("证据状态", value.evidenceState),
            ] + legacyFields(
                related: related,
                values: [("支持证据", value.evidenceRefs)]
            ), links: related.filter { $0.relation == "支持证据" }),
            DetailFields.section("适用范围", json(value.scope, prefix: "范围")),
        ]
    }

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
                "配置版本",
                value.configurationRevision.map(String.init)
            ),
            DetailFields.field("试验阶段", value.trialStage),
            DetailFields.field("试验角色", value.trialRole),
            DetailFields.field("样本", value.sampleRef),
            DetailFields.field("样本开始", value.sampleStart),
            DetailFields.field("样本结束", value.sampleEnd),
            DetailFields.field("RunSpec 哈希", value.runSpecHash),
        ])]
    }

    static func delta(
        _ value: ResearchAuditObjectPayload?
    ) -> [ResearchDocumentReferenceSection] {
        guard let value else { return [] }
        return [DetailFields.section("状态变化", [
            DetailFields.field("对象类型", value.objectKind),
            DetailFields.field("对象 ID", value.objectID),
            DetailFields.field("原状态", value.fromState),
            DetailFields.field("新状态", value.toState),
            DetailFields.field("研究记录", value.traceRef),
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

    private static func json(
        _ value: ResearchJSONValue?,
        prefix: String
    ) -> [ResearchDocumentReferenceField] {
        value?.referenceFields(prefix: L10n.text(prefix)) ?? []
    }

    private static func legacyFields(
        related: [ResearchDocumentRelatedReference],
        values: [(String, [String]?)]
    ) -> [ResearchDocumentReferenceField] {
        values.compactMap { name, refs in
            guard !related.contains(where: { $0.relation == name }) else {
                return nil
            }
            return DetailFields.values(name, refs)
        }
    }
}
