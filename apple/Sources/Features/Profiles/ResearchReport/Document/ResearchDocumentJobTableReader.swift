import Foundation

struct ResearchDocumentJobTablePage {
    let columns: [String]
    let rows: [[String]]
    let hasMore: Bool
}

enum ResearchDocumentJobTableReader {
    static let pageSize = 200
    private static let maximumJSONBytes = 8 * 1024 * 1024

    static func load(
        source: ResearchDocumentTableSource, page: Int
    ) async throws -> ResearchDocumentJobTablePage {
        try await Task.detached {
            let url = try artifactURL(source)
            return try PersonalWorkspaceAccessStore.withAccess(to: url) {
                if source.contentType == "text/csv" {
                    return try csvPage(url: url, page: page)
                }
                return try jsonPage(url: url, page: page)
            }
        }.value
    }

    private static func artifactURL(_ source: ResearchDocumentTableSource) throws -> URL {
        guard source.filename == URL(fileURLWithPath: source.filename).lastPathComponent,
              source.jobID.range(
                of: #"^[A-Za-z0-9._-]{1,128}$"#,
                options: .regularExpression
              ) != nil else { throw ReaderError.invalidSource }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/FactorTester/jobs", isDirectory: true)
            .appendingPathComponent(source.jobID, isDirectory: true)
            .appendingPathComponent(source.filename, isDirectory: false)
    }

    private static func csvPage(
        url: URL, page: Int
    ) throws -> ResearchDocumentJobTablePage {
        let reader = try ResearchDocumentCSVPageReader(url: url)
        guard let header = try reader.nextRow() else { throw ReaderError.empty }
        let start = page * pageSize
        for _ in 0..<start { guard try reader.nextRow() != nil else { break } }
        var rows: [[String]] = []
        for _ in 0..<pageSize {
            guard let row = try reader.nextRow() else { break }
            rows.append(normalize(row, width: header.count))
        }
        return .init(columns: header, rows: rows, hasMore: try reader.nextRow() != nil)
    }

    private static func jsonPage(
        url: URL, page: Int
    ) throws -> ResearchDocumentJobTablePage {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard let size = attributes[.size] as? NSNumber,
              size.intValue <= maximumJSONBytes else {
            throw ReaderError.jsonTooLarge
        }
        let data = try Data(contentsOf: url, options: .mappedIfSafe)
        let value = try JSONSerialization.jsonObject(with: data)
        let (columns, allRows) = jsonRows(value)
        let start = page * pageSize
        let rows = allRows.dropFirst(start).prefix(pageSize).map {
            normalize($0, width: columns.count)
        }
        return .init(
            columns: columns, rows: rows,
            hasMore: allRows.count > start + rows.count
        )
    }

    private static func jsonRows(_ value: Any) -> ([String], [[String]]) {
        if let object = value as? [String: Any],
           let columns = object["columns"] as? [Any], let rows = object["rows"] as? [[Any]] {
            return (columns.map { String(describing: $0) }, rows.map { $0.map { String(describing: $0) } })
        }
        if let values = value as? [[String: Any]] {
            let columns = Array(Set(values.flatMap(\.keys))).sorted()
            return (columns, values.map { item in columns.map { String(describing: item[$0] ?? "") } })
        }
        return (["value"], [[String(describing: value)]])
    }

    private static func normalize(_ row: [String], width: Int) -> [String] {
        Array(row.prefix(width)) + Array(repeating: "", count: max(0, width - row.count))
    }
}

private enum ReaderError: LocalizedError {
    case invalidSource, empty, jsonTooLarge
    var errorDescription: String? {
        switch self {
        case .invalidSource: return L10n.text("完整表格来源无效")
        case .empty: return L10n.text("完整表格为空")
        case .jsonTooLarge: return L10n.text("完整 JSON 表格过大，请使用 CSV 生成物")
        }
    }
}
