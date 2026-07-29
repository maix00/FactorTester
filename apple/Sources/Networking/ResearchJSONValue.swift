import Foundation

enum ResearchJSONValue: Decodable {
    case object([String: ResearchJSONValue])
    case array([ResearchJSONValue])
    case string(String)
    case number(Double)
    case boolean(Bool)
    case null

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if value.decodeNil() { self = .null }
        else if let item = try? value.decode(Bool.self) { self = .boolean(item) }
        else if let item = try? value.decode(Double.self) { self = .number(item) }
        else if let item = try? value.decode(String.self) { self = .string(item) }
        else if let item = try? value.decode([ResearchJSONValue].self) {
            self = .array(item)
        } else {
            self = .object(try value.decode([String: ResearchJSONValue].self))
        }
    }

    var scalarText: String? {
        switch self {
        case let .string(value): return value
        case let .number(value):
            return value.rounded() == value ? String(Int(value)) : String(value)
        case let .boolean(value): return value ? L10n.text("是") : L10n.text("否")
        case .null: return nil
        case let .array(values):
            return values.compactMap(\.scalarText).joined(separator: "、")
        case .object: return nil
        }
    }

}
