import Foundation

struct ResearchDocumentListItem: Identifiable {
    let id: Int
    let depth: Int
    let marker: String
    let text: String
}

enum ResearchDocumentTextBlock {
    case text(String)
    case list([ResearchDocumentListItem])
    case code(language: String, source: String)
    case table(columns: [String], rows: [[String]])
    case math(latex: String)
}

extension ResearchDocumentParser {
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
        while index < lines.count {
            let trimmed = lines[index].trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.hasPrefix("```") {
                guard let end = lines[(index + 1)...].firstIndex(where: {
                    $0.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("```")
                }) else { prose.append(lines[index]); index += 1; continue }
                flushProse()
                let language = String(trimmed.dropFirst(3))
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                blocks.append(.code(
                    language: language.isEmpty ? "text" : language,
                    source: lines[(index + 1)..<end].joined(separator: "\n")
                ))
                index = end + 1
                continue
            }
            if let math = displayMath(lines, at: index) {
                flushProse()
                blocks.append(.math(latex: math.latex))
                index = math.nextIndex
                continue
            }
            if let item = listItem(lines[index], id: index) {
                flushProse()
                var items = [item]
                index += 1
                while index < lines.count, let next = listItem(lines[index], id: index) {
                    items.append(next)
                    index += 1
                }
                blocks.append(.list(items))
                continue
            }
            let columns = tableCells(lines[index])
            let divider = index + 1 < lines.count ? tableCells(lines[index + 1]) : []
            if isTableDivider(divider, columns: columns) {
                flushProse()
                var end = index + 2
                while end < lines.count, tableCells(lines[end]).count == columns.count {
                    end += 1
                }
                blocks.append(.table(
                    columns: columns,
                    rows: (index + 2..<end).map { tableCells(lines[$0]) }
                ))
                index = end
                continue
            }
            prose.append(lines[index])
            index += 1
        }
        flushProse()
        return blocks.isEmpty ? [.text(value)] : blocks
    }

    private static func tableCells(_ line: String) -> [String] {
        var characters = Array(line.trimmingCharacters(
            in: .whitespacesAndNewlines
        ))
        if characters.first == "|" { characters.removeFirst() }
        if characters.last == "|" { characters.removeLast() }
        var values: [String] = []
        var current = ""
        var code = false
        var math: String?
        var index = 0
        while index < characters.count {
            let character = characters[index]
            let following = index + 1 < characters.count
                ? characters[index + 1] : nil
            if math == nil, character == "`" {
                code.toggle()
                current.append(character)
                index += 1
                continue
            }
            if !code, character == "\\", let following {
                let pair = String([character, following])
                switch (math, pair) {
                case (nil, "\\("), (nil, "\\["):
                    math = pair
                case ("\\(", "\\)"), ("\\[", "\\]"):
                    math = nil
                default:
                    break
                }
                current.append(contentsOf: pair)
                index += 2
                continue
            }
            if !code, character == "$", following == "$" {
                math = math == "$$" ? nil : "$$"
                current.append("$")
                current.append("$")
                index += 2
                continue
            }
            if character == "|", !code, math == nil {
                values.append(current.trimmingCharacters(
                    in: .whitespacesAndNewlines
                ))
                current = ""
            } else {
                current.append(character)
            }
            index += 1
        }
        values.append(current.trimmingCharacters(in: .whitespacesAndNewlines))
        return values
    }

    private static func isTableDivider(_ divider: [String], columns: [String]) -> Bool {
        columns.count > 1 && divider.count == columns.count && divider.allSatisfy {
            $0.replacingOccurrences(of: "-", with: "")
                .replacingOccurrences(of: ":", with: "").isEmpty
        }
    }

    private static func listItem(_ line: String, id: Int) -> ResearchDocumentListItem? {
        let indentation = line.prefix { $0 == " " || $0 == "\t" }
        let trimmed = line.dropFirst(indentation.count)
        if let marker = trimmed.first, ["-", "*", "+"].contains(marker),
           trimmed.dropFirst().first?.isWhitespace == true {
            return .init(id: id, depth: indentation.count / 2,
                         marker: String(marker), text: String(trimmed.dropFirst(2)))
        }
        let parts = trimmed.split(maxSplits: 1, whereSeparator: \.isWhitespace)
        guard parts.count == 2, let tail = parts[0].last,
              tail == "." || tail == ")",
              parts[0].dropLast().allSatisfy(\.isNumber) else { return nil }
        return .init(id: id, depth: indentation.count / 2,
                     marker: String(parts[0]), text: String(parts[1]))
    }

    private static func displayMath(
        _ lines: [String], at index: Int
    ) -> (latex: String, nextIndex: Int)? {
        let trimmed = lines[index].trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed == "$$" {
            guard let end = lines[(index + 1)...].firstIndex(where: {
                $0.trimmingCharacters(in: .whitespacesAndNewlines) == "$$"
            }) else { return nil }
            return (lines[(index + 1)..<end].joined(separator: "\n"), end + 1)
        }
        guard trimmed.hasPrefix("\\[") else { return nil }
        if trimmed.hasSuffix("\\]") && trimmed.count >= 4 {
            return (String(trimmed.dropFirst(2).dropLast(2)), index + 1)
        }
        guard let end = lines[(index + 1)...].firstIndex(where: {
            $0.trimmingCharacters(in: .whitespacesAndNewlines).hasSuffix("\\]")
        }) else { return nil }
        var values = [String(trimmed.dropFirst(2))]
        values.append(contentsOf: lines[(index + 1)..<end])
        values.append(String(lines[end].trimmingCharacters(
            in: .whitespacesAndNewlines
        ).dropLast(2)))
        return (values.joined(separator: "\n"), end + 1)
    }
}
