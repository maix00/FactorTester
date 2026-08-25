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
                    "证据状态", lifecycleStatus(detail?.lifecycle.status)
                ),
                DetailFields.field(
                    "生命周期理由",
                    detail?.lifecycle.latestTransition?.reasonZH
                ),
                DetailFields.field(
                    "更新时间",
                    lifecycleUpdatedAt(detail?.lifecycle.latestTransition)
                ),
                DetailFields.field(
                    "检验假设数量",
                    payload.hypothesesTested.map(String.init)
                ),
                DetailFields.field("停止条件", payload.stopCondition),
            ] + localized(payload.facts, prefix: "事实")),
            DetailFields.section(
                "适用范围",
                applicability(detail) + DetailFields.unique([
                    DetailFields.values("限制", payload.limitations),
                    DetailFields.values("冲突", payload.conflicts),
                ]),
                links: factorLinks(detail)
            ),
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
        guard case let .object(values) = detail?.applicability else {
            return localized(detail?.applicability, prefix: "")
        }
        return localized(
            .object(values.filter {
                $0.key != "factor_refs" && $0.key != "factor_subjects"
            }),
            prefix: ""
        )
    }

    private static func factorLinks(
        _ detail: ResearchEvidenceDetailPayload?
    ) -> [ResearchDocumentRelatedReference] {
        guard case let .object(values) = detail?.applicability,
              case let .array(subjects) = values["factor_subjects"] else {
            return []
        }
        return subjects.compactMap { value in
            guard case let .object(subject) = value,
                  let targetRef = subject["ref"]?.scalarText,
                  targetRef.hasPrefix("factor:v2:"),
                  let label = subject["alias"]?.scalarText,
                  !label.isEmpty else { return nil }
            return .init(
                relation: L10n.text("适用因子"),
                reference: .init(
                    kind: "factor",
                    targetRef: targetRef,
                    label: label
                ),
                detailFields: []
            )
        }
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

    private static func lifecycleStatus(_ status: String?) -> String? {
        switch status {
        case "active": L10n.text("可发现")
        case "excluded": L10n.text("已排除")
        case .none: nil
        default: status
        }
    }

    private static func lifecycleUpdatedAt(
        _ transition: ResearchEvidenceLifecycleTransition?
    ) -> String? {
        guard let transition else { return nil }
        return Date(timeIntervalSince1970: transition.updatedAt).formatted(
            date: .abbreviated,
            time: .shortened
        )
    }
}
