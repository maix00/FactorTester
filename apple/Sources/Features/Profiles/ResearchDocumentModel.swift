import Foundation

enum ResearchDocumentContent {
    case none
    case text(String)
    case code(language: String, source: String)
    case math(latex: String, fallback: String)
    case table(
        columns: [String], rows: [[String]], source: ResearchDocumentTableSource?
    )
    case image(assetRef: String)
    case json(String)
}

struct ResearchDocumentAsset: Identifiable {
    let id: String
    let assetRef: String
    let mediaType: String
    let filename: String
    let caption: String
    let altText: String
    let contentHash: String
    let externalRef: String
    let localRef: String
}

struct ResearchDocumentBinding: Identifiable {
    let id: String
    let componentID: String
    let kind: String
    let targetRef: String
    let label: String
    let detailFields: [ResearchDocumentReferenceField]
}

struct ResearchDocumentComponent: Identifiable {
    let id: String
    let kind: String
    let displayKind: String
    let parentID: String?
    let title: String
    let body: String
    let content: ResearchDocumentContent
}

enum ResearchDocumentParser {
    static func parseComponent(
        _ value: [String: Any]
    ) -> ResearchDocumentComponent? {
        guard let id = value["component_id"] as? String,
              let kind = value["kind"] as? String,
              let title = value["title"] as? String else { return nil }
        let displayKind = value["display_kind"] as? String ?? ""
        let raw = value["content"]
        return ResearchDocumentComponent(
            id: id,
            kind: kind,
            displayKind: displayKind,
            parentID: value["parent_id"] as? String,
            title: title,
            body: value["body"] as? String ?? "",
            content: content(kind: kind, displayKind: displayKind, raw: raw)
        )
    }

    static func parseAsset(_ value: [String: Any]) -> ResearchDocumentAsset? {
        guard let assetRef = value["asset_ref"] as? String,
              let filename = value["filename"] as? String else { return nil }
        return ResearchDocumentAsset(
            id: assetRef,
            assetRef: assetRef,
            mediaType: value["media_type"] as? String ?? "application/octet-stream",
            filename: filename,
            caption: value["caption"] as? String ?? "",
            altText: value["alt_text"] as? String ?? "",
            contentHash: value["content_hash"] as? String ?? "",
            externalRef: value["external_ref"] as? String ?? "",
            localRef: value["local_ref"] as? String ?? ""
        )
    }

    static func parseBinding(_ value: [String: Any]) -> ResearchDocumentBinding? {
        guard let id = value["binding_id"] as? String,
              let componentID = value["component_id"] as? String,
              let kind = value["kind"] as? String,
              let targetRef = value["target_ref"] as? String else { return nil }
        return ResearchDocumentBinding(
            id: id,
            componentID: componentID,
            kind: kind,
            targetRef: targetRef,
            label: value["label"] as? String ?? "",
            detailFields: ResearchDocumentReferenceFields.parse(value["data"])
        )
    }

    private static func content(
        kind: String, displayKind: String, raw: Any?
    ) -> ResearchDocumentContent {
        guard let raw else { return .none }
        if let text = raw as? String {
            return text.isEmpty ? .none : .text(text)
        }
        guard let object = raw as? [String: Any] else {
            return .json(stringify(raw))
        }
        if let table = ResearchDocumentTableParser.parse(object) {
            return .table(columns: table.columns, rows: table.rows, source: table.source)
        }
        if let assetRef = object["asset_ref"] as? String {
            return .image(assetRef: assetRef)
        }
        if let code = object["code"] as? String {
            return .code(language: object["language"] as? String ?? "text", source: code)
        }
        if let latex = object["latex"] as? String {
            return .math(latex: latex, fallback: object["fallback"] as? String ?? "")
        }
        if kind == "special" && displayKind == "display_math",
           let formula = object["formula"] as? String {
            return .math(latex: formula, fallback: object["fallback"] as? String ?? "")
        }
        return .json(stringify(object))
    }

    private static func stringify(_ value: Any) -> String {
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]),
              let text = String(data: data, encoding: .utf8) else { return String(describing: value) }
        return text
    }
}
