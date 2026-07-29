import Foundation

struct ResearchDocumentReferenceField: Identifiable, Hashable {
    let name: String
    let value: String

    var id: String { "\(name)\u{1f}\(value)" }
}

enum ResearchDocumentReferenceFields {
    static func parse(_ raw: Any?) -> [ResearchDocumentReferenceField] {
        guard let object = raw as? [String: Any] else { return [] }
        var fields: [ResearchDocumentReferenceField] = []
        flatten(object, prefix: "", depth: 0, into: &fields)
        return Array(fields.prefix(32))
    }

    private static func flatten(
        _ object: [String: Any],
        prefix: String,
        depth: Int,
        into fields: inout [ResearchDocumentReferenceField]
    ) {
        guard depth <= 2 else { return }
        for key in object.keys.sorted() {
            let name = prefix.isEmpty ? key : "\(prefix).\(key)"
            guard let value = object[key] else { continue }
            if let child = value as? [String: Any] {
                flatten(child, prefix: name, depth: depth + 1, into: &fields)
            } else if let text = displayValue(value) {
                fields.append(.init(name: name, value: text))
            }
        }
    }

    private static func displayValue(_ value: Any) -> String? {
        if value is NSNull { return nil }
        if let text = value as? String { return bounded(text) }
        if let number = value as? NSNumber { return number.stringValue }
        if let values = value as? [String] {
            return bounded(values.joined(separator: "、"))
        }
        return nil
    }

    private static func bounded(_ value: String) -> String {
        String(value.prefix(1_000))
    }
}
