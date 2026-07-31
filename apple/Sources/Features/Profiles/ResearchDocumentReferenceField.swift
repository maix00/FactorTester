import Foundation

struct ResearchDocumentReferenceField: Identifiable, Hashable {
    let name: String
    let value: String

    var id: String { "\(name)\u{1f}\(value)" }
}

enum ResearchDocumentReferenceFields {
    static func parse(_ raw: Any?) -> [ResearchDocumentReferenceField] {
        guard var object = raw as? [String: Any] else { return [] }
        if object["related_references"] != nil {
            object.removeValue(forKey: "related_references")
            object.removeValue(forKey: "member_refs")
        }
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

enum ResearchDocumentRelatedReferences {
    static func parse(
        _ raw: Any?, componentID: String
    ) -> [ResearchDocumentRelatedReference] {
        guard let object = raw as? [String: Any],
              let values = object["related_references"] as? [[String: Any]]
        else { return [] }
        return values.compactMap { value in
            guard let kind = value["kind"] as? String,
                  let targetRef = value["target_ref"] as? String,
                  let label = value["label"] as? String,
                  ResearchDocumentReferenceCatalog.contains(kind)
            else { return nil }
            return ResearchDocumentRelatedReference(
                relation: value["relation"] as? String ?? L10n.text("关联对象"),
                reference: .init(
                    kind: kind,
                    targetRef: targetRef,
                    label: label,
                    componentID: componentID
                ),
                detailFields: ResearchDocumentReferenceFields.parse(value["data"])
            )
        }
    }
}
