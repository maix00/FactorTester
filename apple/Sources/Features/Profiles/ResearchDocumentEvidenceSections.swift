import Foundation

enum ResearchDocumentEvidenceSections {
    static func make(
        payload: ResearchAuditObjectPayload?,
        detail: ResearchEvidenceDetailPayload?
    ) -> [ResearchDocumentReferenceSection] {
        guard let payload else { return [] }
        return [
            DetailFields.section("研究含义", [
                DetailFields.field("证据标题", payload.title),
                DetailFields.field("证明内容", payload.claimSummary),
                DetailFields.field("证据类型", payload.evidenceKind),
                DetailFields.field(
                    "检验假设数量",
                    payload.hypothesesTested.map(String.init)
                ),
                DetailFields.field("停止条件", payload.stopCondition),
            ] + localized(payload.facts, prefix: "事实")),
            DetailFields.section("适用范围", applicability(detail)
                + DetailFields.unique([
                    DetailFields.values("限制", payload.limitations),
                    DetailFields.values("冲突", payload.conflicts),
                ])),
            DetailFields.section("来源与审计", DetailFields.unique([
                DetailFields.values("来源", payload.sourceRefs),
                DetailFields.values("指标", payload.metricRefs),
                DetailFields.values("生成物", payload.artifactRefs),
                DetailFields.field("证据包 ID", payload.envelopeID),
                DetailFields.field("证据哈希", payload.envelopeHash),
                DetailFields.field("登记时间", createdAt(detail)),
            ]) + localized(payload.identityRefs, prefix: "身份")),
        ]
    }

    private static func applicability(
        _ detail: ResearchEvidenceDetailPayload?
    ) -> [ResearchDocumentReferenceField] {
        localized(detail?.applicability, prefix: "")
    }

    private static func localized(
        _ value: ResearchJSONValue?,
        prefix: String
    ) -> [ResearchDocumentReferenceField] {
        value?.referenceFields(prefix: L10n.text(prefix)) ?? []
    }

    private static func createdAt(
        _ detail: ResearchEvidenceDetailPayload?
    ) -> String? {
        guard let detail else { return nil }
        return Date(timeIntervalSince1970: detail.createdAt).formatted(
            date: .abbreviated,
            time: .shortened
        )
    }
}
