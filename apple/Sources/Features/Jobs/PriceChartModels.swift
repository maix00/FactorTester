import Foundation

struct PriceBar: Identifiable, Hashable {
    let id: Int
    let timestamp: Date
    let open: Double
    let high: Double
    let low: Double
    let close: Double
    let volume: Double

    var isUp: Bool { close >= open }
}

enum PriceBarDecoder {
    static func decodeJSON(_ data: Data) -> [PriceBar] {
        guard let value = try? JSONSerialization.jsonObject(with: data) else { return [] }
        return decode(value)
    }

    static func decode(_ value: Any?) -> [PriceBar] {
        guard let rows = firstRows(in: value) else { return [] }
        let decoded: [PriceBar] = rows.enumerated().compactMap { item in
            let index = item.offset
            let row = item.element
            guard let timestamp = number(row, aliases: ["timestamp", "time", "datetime", "date"]),
                  let open = number(row, aliases: ["open", "o"]),
                  let high = number(row, aliases: ["high", "h"]),
                  let low = number(row, aliases: ["low", "l"]),
                  let close = number(row, aliases: ["close", "c"]),
                  high >= max(open, close), low <= min(open, close) else { return nil }
            return PriceBar(
                id: index,
                timestamp: Date(timeIntervalSince1970: timestamp > 20_000_000_000 ? timestamp / 1000 : timestamp),
                open: open,
                high: high,
                low: low,
                close: close,
                volume: number(row, aliases: ["volume", "vol", "成交量"]) ?? 0
            )
        }
        return decoded.sorted { $0.timestamp < $1.timestamp }.enumerated().map { item in
            let index = item.offset
            let bar = item.element
            return PriceBar(id: index, timestamp: bar.timestamp, open: bar.open, high: bar.high, low: bar.low, close: bar.close, volume: bar.volume)
        }
    }

    private static func firstRows(in value: Any?, depth: Int = 0) -> [[String: Any]]? {
        guard depth < 8 else { return nil }
        if let rows = value as? [[String: Any]], rows.contains(where: isOHLCRow) { return rows }
        if let object = value as? [String: Any] {
            for child in object.values {
                if let rows = firstRows(in: child, depth: depth + 1) { return rows }
            }
        }
        if let array = value as? [Any] {
            for child in array {
                if let rows = firstRows(in: child, depth: depth + 1) { return rows }
            }
        }
        return nil
    }

    private static func isOHLCRow(_ row: [String: Any]) -> Bool {
        number(row, aliases: ["open", "o"]) != nil &&
        number(row, aliases: ["high", "h"]) != nil &&
        number(row, aliases: ["low", "l"]) != nil &&
        number(row, aliases: ["close", "c"]) != nil
    }

    private static func number(_ row: [String: Any], aliases: [String]) -> Double? {
        let normalized = Dictionary(uniqueKeysWithValues: row.map { (normalize($0.key), $0.value) })
        for alias in aliases {
            guard let value = normalized[normalize(alias)] else { continue }
            if let number = value as? NSNumber { return number.doubleValue }
            if let text = value as? String, let number = Double(text) { return number }
        }
        return nil
    }

    private static func normalize(_ value: String) -> String {
        value.lowercased().filter { $0.isLetter || $0.isNumber }
    }
}
