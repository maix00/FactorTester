import Foundation

struct PriceBar: Identifiable, Hashable, Sendable {
    let id: Int
    let timestamp: Date
    let open: Double
    let high: Double
    let low: Double
    let close: Double
    let volume: Double

    var isUp: Bool { close >= open }
}

enum PriceBarDecodingError: Error, Equatable {
    case inputTooLarge(maximumByteCount: Int)
    case rowLimitExceeded(maximumRowCount: Int)
    case invalidJSON
    case missingOHLCVRows
}

enum PriceBarDecoder {
    struct Limits: Equatable, Sendable {
        let maximumInputByteCount: Int
        let maximumRowCount: Int

        static let production = Limits(
            maximumInputByteCount: 64 * 1_024 * 1_024,
            maximumRowCount: 250_000
        )
    }

    static func decodeJSON(_ data: Data) -> [PriceBar] {
        (try? decodeJSON(data, limits: .production)) ?? []
    }

    static func decodeJSONInBackground(
        _ data: Data,
        limits: Limits = .production
    ) async throws -> [PriceBar] {
        let worker = Task.detached(priority: .userInitiated) {
            try decodeJSON(data, limits: limits)
        }
        return try await withTaskCancellationHandler {
            try await worker.value
        } onCancel: {
            worker.cancel()
        }
    }

    static func decodeJSON(_ data: Data, limits: Limits) throws -> [PriceBar] {
        guard data.count <= limits.maximumInputByteCount else {
            throw PriceBarDecodingError.inputTooLarge(
                maximumByteCount: limits.maximumInputByteCount
            )
        }
        try Task.checkCancellation()
        let value: Any
        do {
            value = try JSONSerialization.jsonObject(with: data)
        } catch {
            throw PriceBarDecodingError.invalidJSON
        }
        try Task.checkCancellation()
        return try decode(value, limits: limits)
    }

    static func decode(_ value: Any?) -> [PriceBar] {
        (try? decode(value, limits: .production)) ?? []
    }

    private static func decode(_ value: Any?, limits: Limits) throws -> [PriceBar] {
        guard let rows = try firstRows(in: value, limits: limits) else {
            throw PriceBarDecodingError.missingOHLCVRows
        }
        var decoded: [PriceBar] = []
        decoded.reserveCapacity(rows.count)
        for item in rows.enumerated() {
            if item.offset.isMultiple(of: 256) {
                try Task.checkCancellation()
            }
            let index = item.offset
            let row = item.element
            let normalized = normalizedRow(row)
            guard let timestamp = number(
                normalized, aliases: ["timestamp", "time", "datetime", "date"]
            ),
            let open = number(normalized, aliases: ["open", "o"]),
            let high = number(normalized, aliases: ["high", "h"]),
            let low = number(normalized, aliases: ["low", "l"]),
            let close = number(normalized, aliases: ["close", "c"]),
            timestamp.isFinite, open.isFinite, high.isFinite,
            low.isFinite, close.isFinite,
            high >= max(open, close), low <= min(open, close) else { continue }
            let volume = number(
                normalized, aliases: ["volume", "vol", "成交量"]
            ) ?? 0
            guard volume.isFinite else { continue }
            decoded.append(PriceBar(
                id: index,
                timestamp: Date(timeIntervalSince1970: timestamp > 20_000_000_000 ? timestamp / 1000 : timestamp),
                open: open,
                high: high,
                low: low,
                close: close,
                volume: volume
            ))
        }
        try Task.checkCancellation()
        decoded.sort { $0.timestamp < $1.timestamp }
        try Task.checkCancellation()
        return decoded.enumerated().map { item in
            let index = item.offset
            let bar = item.element
            return PriceBar(id: index, timestamp: bar.timestamp, open: bar.open, high: bar.high, low: bar.low, close: bar.close, volume: bar.volume)
        }
    }

    private static func firstRows(
        in value: Any?, limits: Limits, depth: Int = 0
    ) throws -> [[String: Any]]? {
        try Task.checkCancellation()
        guard depth < 8 else { return nil }
        if let rows = value as? [[String: Any]] {
            for item in rows.enumerated() {
                if item.offset.isMultiple(of: 256) {
                    try Task.checkCancellation()
                }
                if isOHLCRow(item.element) {
                    guard rows.count <= limits.maximumRowCount else {
                        throw PriceBarDecodingError.rowLimitExceeded(
                            maximumRowCount: limits.maximumRowCount
                        )
                    }
                    return rows
                }
            }
        }
        if let object = value as? [String: Any] {
            for child in object.values {
                if let rows = try firstRows(
                    in: child, limits: limits, depth: depth + 1
                ) { return rows }
            }
        }
        if let array = value as? [Any] {
            for item in array.enumerated() {
                if item.offset.isMultiple(of: 256) {
                    try Task.checkCancellation()
                }
                if let rows = try firstRows(
                    in: item.element, limits: limits, depth: depth + 1
                ) { return rows }
            }
        }
        return nil
    }

    private static func isOHLCRow(_ row: [String: Any]) -> Bool {
        let normalized = normalizedRow(row)
        return number(normalized, aliases: ["open", "o"]) != nil &&
        number(normalized, aliases: ["high", "h"]) != nil &&
        number(normalized, aliases: ["low", "l"]) != nil &&
        number(normalized, aliases: ["close", "c"]) != nil
    }

    private static func number(
        _ normalizedRow: [String: Any], aliases: [String]
    ) -> Double? {
        for alias in aliases {
            guard let value = normalizedRow[alias] else { continue }
            if let number = value as? NSNumber { return number.doubleValue }
            if let text = value as? String, let number = Double(text) { return number }
        }
        return nil
    }

    private static func normalizedRow(_ row: [String: Any]) -> [String: Any] {
        row.reduce(into: [:]) { normalized, field in
            normalized[normalize(field.key)] = field.value
        }
    }

    private static func normalize(_ value: String) -> String {
        value.lowercased().filter { $0.isLetter || $0.isNumber }
    }
}
