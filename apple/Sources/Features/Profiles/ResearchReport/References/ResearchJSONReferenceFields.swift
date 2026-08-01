import Foundation

extension ResearchJSONValue {
    func referenceFields(prefix: String = "") -> [ResearchDocumentReferenceField] {
        switch self {
        case let .object(values):
            return values.keys.sorted().flatMap { key in
                values[key]?.referenceFields(
                    prefix: prefix.isEmpty
                        ? ResearchReferenceFieldLabels.title(key)
                        : "\(prefix) · \(ResearchReferenceFieldLabels.title(key))"
                ) ?? []
            }
        case let .array(values):
            let text = values.compactMap(\.scalarText).joined(separator: "、")
            return text.isEmpty ? [] : [.init(name: prefix, value: text)]
        default:
            return scalarText.map { [.init(name: prefix, value: $0)] } ?? []
        }
    }
}

private enum ResearchReferenceFieldLabels {
    static func title(_ key: String) -> String {
        let values = [
            "product_group": "产品组",
            "product_refs": "产品",
            "source_refs": "数据来源",
            "factor_refs": "因子",
            "sample_refs": "样本",
            "time_window": "时间范围",
            "start": "开始",
            "end": "结束",
            "limitations": "限制",
            "rule_ref": "规则",
            "contract_hash": "研究合同",
            "methodology_hash": "方法",
            "trial_plan_hash": "试验计划",
            "run_spec_hash": "运行配置",
        ]
        return L10n.text(values[key] ?? key.replacingOccurrences(
            of: "_",
            with: " "
        ))
    }
}
