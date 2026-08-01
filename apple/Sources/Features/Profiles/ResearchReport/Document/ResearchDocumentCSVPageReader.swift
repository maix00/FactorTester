import Foundation

final class ResearchDocumentCSVPageReader {
    private static let maximumFieldBytes = 1_024 * 1_024
    private let stream: InputStream
    private var buffer = [UInt8](repeating: 0, count: 64 * 1024)
    private var readCount = 0
    private var cursor = 0
    private var lookahead: UInt8?

    init(url: URL) throws {
        guard let stream = InputStream(url: url) else {
            throw CocoaError(.fileNoSuchFile)
        }
        self.stream = stream
        stream.open()
        if let error = stream.streamError { throw error }
    }

    deinit { stream.close() }

    func nextRow() throws -> [String]? {
        var rows: [String] = []
        var field = Data()
        var quoted = false
        var sawByte = false
        while let byte = try nextByte() {
            sawByte = true
            if quoted {
                if byte == 34, try peekByte() == 34 {
                    _ = try nextByte()
                    field.append(34)
                } else if byte == 34 {
                    quoted = false
                } else {
                    try append(byte, to: &field)
                }
                continue
            }
            switch byte {
            case 34 where field.isEmpty:
                quoted = true
            case 44:
                rows.append(string(field)); field.removeAll(keepingCapacity: true)
            case 10:
                rows.append(string(field)); return rows
            case 13:
                if try peekByte() == 10 { _ = try nextByte() }
                rows.append(string(field)); return rows
            default:
                try append(byte, to: &field)
            }
        }
        guard sawByte else { return nil }
        rows.append(string(field))
        return rows
    }

    private func nextByte() throws -> UInt8? {
        if let lookahead { self.lookahead = nil; return lookahead }
        return try rawByte()
    }

    private func peekByte() throws -> UInt8? {
        if lookahead == nil { lookahead = try rawByte() }
        return lookahead
    }

    private func rawByte() throws -> UInt8? {
        if cursor >= readCount {
            readCount = buffer.withUnsafeMutableBufferPointer {
                guard let baseAddress = $0.baseAddress else { return 0 }
                return stream.read(baseAddress, maxLength: $0.count)
            }
            cursor = 0
            if readCount < 0 { throw stream.streamError ?? CocoaError(.fileReadUnknown) }
            if readCount == 0 { return nil }
        }
        defer { cursor += 1 }
        return buffer[cursor]
    }

    private func string(_ data: Data) -> String {
        String(data: data, encoding: .utf8) ?? ""
    }

    private func append(_ byte: UInt8, to field: inout Data) throws {
        guard field.count < Self.maximumFieldBytes else {
            throw ResearchDocumentCSVPageReaderError.fieldTooLarge
        }
        field.append(byte)
    }
}

private enum ResearchDocumentCSVPageReaderError: LocalizedError {
    case fieldTooLarge

    var errorDescription: String? {
        switch self {
        case .fieldTooLarge: return L10n.text("CSV 单元格超过本地读取上限")
        }
    }
}
