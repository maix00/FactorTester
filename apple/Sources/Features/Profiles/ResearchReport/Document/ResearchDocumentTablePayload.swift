import Foundation

struct ResearchDocumentTableSource: Equatable {
    let jobID: String
    let artifactRef: String
    let filename: String
    let contentType: String
    let contentHash: String
    let isTruncated: Bool
}

struct ResearchDocumentTablePayload {
    let columns: [String]
    let rows: [[String]]
    let source: ResearchDocumentTableSource?
}

enum ResearchDocumentTableParser {
    static func parse(_ object: [String: Any]) -> ResearchDocumentTablePayload? {
        guard let rawColumns = object["columns"] as? [Any],
              let rawRows = object["rows"] as? [[Any]], !rawColumns.isEmpty else {
            return nil
        }
        let columns = rawColumns.map { String(describing: $0) }
        let rows = rawRows.map { row in
            row.prefix(columns.count).map { String(describing: $0) }
        }
        guard rows.allSatisfy({ $0.count == columns.count }) else { return nil }
        return ResearchDocumentTablePayload(
            columns: columns,
            rows: rows,
            source: source(from: object)
        )
    }

    private static func source(from object: [String: Any]) -> ResearchDocumentTableSource? {
        guard let raw = object["source"] as? [String: Any],
              let jobID = raw["job_id"] as? String,
              let artifactRef = raw["artifact_ref"] as? String,
              let filename = raw["filename"] as? String,
              let contentType = raw["content_type"] as? String,
              let contentHash = raw["content_hash"] as? String,
              validID(jobID), filename == URL(fileURLWithPath: filename).lastPathComponent,
              !filename.isEmpty else { return nil }
        let preview = object["preview"] as? [String: Any]
        return ResearchDocumentTableSource(
            jobID: jobID,
            artifactRef: artifactRef,
            filename: filename,
            contentType: contentType,
            contentHash: contentHash,
            isTruncated: preview?["is_truncated"] as? Bool ?? false
        )
    }

    private static func validID(_ value: String) -> Bool {
        value.range(of: #"^[A-Za-z0-9._-]{1,128}$"#,
                    options: .regularExpression) != nil
    }
}
