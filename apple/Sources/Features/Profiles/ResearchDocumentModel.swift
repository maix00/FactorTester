import Foundation

enum ResearchDocumentContent {
    case none
    case text(String)
    case code(language: String, source: String)
    case math(latex: String, fallback: String)
    case table(columns: [String], rows: [[String]])
    case image(assetRef: String)
    case json(String)
}

enum ResearchDocumentTextBlock {
    case text(String)
    case table(columns: [String], rows: [[String]])
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
            label: value["label"] as? String ?? ""
        )
    }

    private static func content(
        kind: String, displayKind: String, raw: Any?
    ) -> ResearchDocumentContent {
        guard let raw else { return .none }
        if let text = raw as? String {
            if let table = markdownTable(text) { return .table(columns: table.0, rows: table.1) }
            if let object = jsonObject(text), let table = tableContent(object) {
                return .table(columns: table.0, rows: table.1)
            }
            return text.isEmpty ? .none : .text(text)
        }
        guard let object = raw as? [String: Any] else {
            return .json(stringify(raw))
        }
        if let table = tableContent(object) {
            return .table(columns: table.0, rows: table.1)
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

    static func textBlocks(_ value: String) -> [ResearchDocumentTextBlock] {
        let lines = value.split(omittingEmptySubsequences: false, whereSeparator: \.isNewline)
            .map(String.init)
        guard lines.count > 1 else { return [.text(value)] }
        var blocks: [ResearchDocumentTextBlock] = []
        var prose: [String] = []
        var index = 0
        func flushProse() {
            let text = prose.joined(separator: "\n")
            if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                blocks.append(.text(text))
            }
            prose.removeAll(keepingCapacity: true)
        }
        func splitLine(_ line: String) -> [String] {
            line.trimmingCharacters(in: .whitespacesAndNewlines)
                .trimmingCharacters(in: CharacterSet(charactersIn: "|"))
                .split(separator: "|", omittingEmptySubsequences: false)
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        }
        while index < lines.count {
            let columns = splitLine(lines[index])
            let separators = index + 1 < lines.count ? splitLine(lines[index + 1]) : []
            let validSeparator = separators.count == columns.count
                && columns.count > 1
                && separators.allSatisfy {
                    $0.replacingOccurrences(of: "-", with: "")
                        .replacingOccurrences(of: ":", with: "").isEmpty
                }
            if validSeparator {
                var end = index + 2
                while end < lines.count && splitLine(lines[end]).count == columns.count {
                    end += 1
                }
                flushProse()
                let rows = (index + 2..<end).map { splitLine(lines[$0]) }
                blocks.append(.table(columns: columns, rows: rows))
                index = end
            } else {
                prose.append(lines[index])
                index += 1
            }
        }
        flushProse()
        return blocks.isEmpty ? [.text(value)] : blocks
    }

    private static func tableContent(_ object: [String: Any]) -> ([String], [[String]])? {
        guard let columns = object["columns"] as? [Any],
              let rows = object["rows"] as? [[Any]], !columns.isEmpty else { return nil }
        let labels = columns.map { String(describing: $0) }
        let values = rows.map { row in
            row.prefix(labels.count).map { String(describing: $0) }
        }
        guard values.allSatisfy({ $0.count == labels.count }) else { return nil }
        return (labels, values)
    }

    static func markdownTable(_ value: String) -> ([String], [[String]])? {
        let lines = value.split(whereSeparator: \.isNewline).map(String.init)
        guard lines.count >= 2 else { return nil }
        let split: (String) -> [String] = { line in
            line.trimmingCharacters(in: .whitespacesAndNewlines)
                .trimmingCharacters(in: CharacterSet(charactersIn: "|"))
                .split(separator: "|", omittingEmptySubsequences: false)
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        }
        let columns = split(lines[0])
        let separator = split(lines[1])
        guard columns.count > 1,
              separator.count == columns.count,
              separator.allSatisfy({ $0.replacingOccurrences(of: "-", with: "").replacingOccurrences(of: ":", with: "").isEmpty }) else { return nil }
        let rows = lines.dropFirst(2).map(split).filter { $0.count == columns.count }
        return (columns, rows)
    }

    private static func jsonObject(_ value: String) -> [String: Any]? {
        guard let data = value.data(using: .utf8) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }

    private static func stringify(_ value: Any) -> String {
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]),
              let text = String(data: data, encoding: .utf8) else { return String(describing: value) }
        return text
    }
}
