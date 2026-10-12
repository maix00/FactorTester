import Foundation

extension ResearchJSONValue {
    func referenceFields(prefix: String) -> [ResearchDocumentReferenceField] {
        switch self {
        case .object:
            return ResearchDocumentReferenceFields.parse(foundationValue).map {
                .init(
                    name: displayName($0.name, prefix: prefix),
                    value: $0.value
                )
            }
        case .null:
            return []
        case .array, .string, .number, .boolean:
            guard let value = scalarText, !value.isEmpty else { return [] }
            return [
                .init(
                    name: prefix.isEmpty ? L10n.text("值") : prefix,
                    value: String(value.prefix(1_000))
                ),
            ]
        }
    }

    private var foundationValue: Any {
        switch self {
        case let .object(values):
            return values.mapValues { $0.foundationValue }
        case let .array(values):
            return values.map { $0.foundationValue }
        case let .string(value): return value
        case let .number(value): return value
        case let .boolean(value): return L10n.text(value ? "是" : "否")
        case .null: return NSNull()
        }
    }

    private func displayName(_ path: String, prefix: String) -> String {
        let labels = path.split(separator: ".").map { component -> String in
            let key = String(component)
            let localized: [String: String] = [
                "product_refs": "产品",
                "time_window": "时间范围",
                "start": "开始",
                "end": "结束",
            ]
            return localized[key.lowercased()].map(L10n.text)
                ?? key.replacingOccurrences(of: "_", with: " ")
        }
        let suffix = labels.joined(separator: " · ")
        return prefix.isEmpty ? suffix : "\(prefix) · \(suffix)"
    }
}
