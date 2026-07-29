import Foundation

enum ResearchDocumentReferenceDetails {
    static func fields(
        reference: ResearchDocumentTypedLink,
        binding: ResearchDocumentBinding?,
        payload: ResearchAuditObjectPayload?
    ) -> [ResearchDocumentReferenceField] {
        var result = [
            field("类型", ResearchDocumentTypedLinkPresentation.title(for: reference.kind)),
            field("名称", reference.label),
            field("对象引用", reference.targetRef),
        ]
        result += binding?.detailFields ?? []
        guard let payload else { return unique(result) }
        append("对象类型", payload.objectKind, to: &result)
        append("对象 ID", payload.objectID, to: &result)
        append("状态", payload.status, to: &result)
        append("原状态", payload.fromState, to: &result)
        append("新状态", payload.toState, to: &result)
        append("重要性", payload.materiality, to: &result)
        append("研究问题", payload.epistemicQuestion, to: &result)
        append("Claim 类型", payload.claimType, to: &result)
        append("证据状态", payload.evidenceState, to: &result)
        append("证据类型", payload.evidenceKind, to: &result)
        append("假设", payload.hypothesisRef, to: &result)
        append("试验族", payload.trialFamily, to: &result)
        append("协议", payload.protocolRef, to: &result)
        append("运行 ID", payload.runID, to: &result)
        append("RunSpec 哈希", payload.runSpecHash, to: &result)
        append("样本", payload.sampleRef, to: &result)
        append("样本开始", payload.sampleStart, to: &result)
        append("样本结束", payload.sampleEnd, to: &result)
        append("摘要", payload.summaryZH, to: &result)
        append("停止条件", payload.stopCondition, to: &result)
        append("来源", payload.sourceRefs, to: &result)
        append("指标", payload.metricRefs, to: &result)
        append("生成物", payload.artifactRefs, to: &result)
        append("限制", payload.limitations, to: &result)
        append("冲突", payload.conflicts, to: &result)
        return unique(result)
    }

    private static func field(
        _ name: String,
        _ value: String
    ) -> ResearchDocumentReferenceField {
        .init(name: L10n.text(name), value: value)
    }

    private static func append(
        _ name: String,
        _ value: String?,
        to fields: inout [ResearchDocumentReferenceField]
    ) {
        guard let value, !value.isEmpty else { return }
        fields.append(field(name, value))
    }

    private static func append(
        _ name: String,
        _ values: [String]?,
        to fields: inout [ResearchDocumentReferenceField]
    ) {
        guard let values, !values.isEmpty else { return }
        fields.append(field(name, values.joined(separator: "、")))
    }

    private static func unique(
        _ fields: [ResearchDocumentReferenceField]
    ) -> [ResearchDocumentReferenceField] {
        var names = Set<String>()
        return fields.filter { names.insert($0.name).inserted }
    }
}
