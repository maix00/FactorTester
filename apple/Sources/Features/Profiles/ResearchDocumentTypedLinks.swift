import Foundation
import SwiftUI
#if os(macOS)
import AppKit
#endif

struct ResearchDocumentTypedLink: Equatable, Hashable, Identifiable {
    let kind: String
    let targetRef: String
    let label: String

    var id: String { "\(kind)\u{1f}\(targetRef)\u{1f}\(label)" }

    var url: URL? {
        guard let encoded = targetRef.addingPercentEncoding(
            withAllowedCharacters: .alphanumerics
        ) else { return nil }
        return URL(string: "factortester://\(kind)/\(encoded)")
    }
}

enum ResearchDocumentTypedLinkParser {
    enum Segment: Equatable {
        case text(String)
        case reference(ResearchDocumentTypedLink)
    }

    private static let expression = try! NSRegularExpression(pattern: #"""
    (?<!\\)\[([^\]\r\n]{1,256})\]\(factortester://([a-z_]+)/([^()\s]+)\)
    |(?<!\\)\[([^\]\r\n]{1,256})\]\((https?://[^\s()]+)\)
    |(?<!\\)\[([^\]\r\n]{1,256})\]\(((?:[^\s\[\]()<>/]+/)+[^\s\[\]()<>/]+\.(?:md|markdown|json|csv|py|txt|pdf|png|jpe?g|svg))\)
    |(?<![`\\\w])(https?://[^\s<>()\]]+)
    |(?<![`\\\w/])((?:[^\s\[\]()<>/]+/)+[^\s\[\]()<>/]+\.(?:md|markdown|json|csv|py|txt|pdf|png|jpe?g|svg))(?![\w/])
    """#, options: [.allowCommentsAndWhitespace, .caseInsensitive])

    private static let inlineCodeExpression = try! NSRegularExpression(
        pattern: #"`+[^`\r\n]*`+"#
    )

    static func segments(in text: String) -> [Segment] {
        let range = NSRange(text.startIndex..., in: text)
        let codeRanges = inlineCodeExpression.matches(in: text, range: range)
            .map(\.range)
        var cursor = text.startIndex
        var result: [Segment] = []
        for match in expression.matches(in: text, range: range) {
            guard !codeRanges.contains(where: {
                NSIntersectionRange($0, match.range).length > 0
            }) else { continue }
            guard let whole = Range(match.range, in: text),
                  cursor <= whole.lowerBound else { continue }
            if cursor < whole.lowerBound {
                result.append(.text(String(text[cursor..<whole.lowerBound])))
            }
            guard let reference = reference(match, in: text) else { continue }
            result.append(.reference(reference))
            cursor = whole.upperBound
        }
        if cursor < text.endIndex { result.append(.text(String(text[cursor...]))) }
        return result.isEmpty ? [.text(text)] : result
    }

    private static func reference(
        _ match: NSTextCheckingResult, in text: String
    ) -> ResearchDocumentTypedLink? {
        if let label = value(match, group: 1, in: text),
           let kind = value(match, group: 2, in: text),
           let target = value(match, group: 3, in: text) {
            return ResearchDocumentTypedLink(
                kind: kind, targetRef: target.removingPercentEncoding ?? target,
                label: label
            )
        }
        if let label = value(match, group: 4, in: text),
           let target = value(match, group: 5, in: text),
           isSafeWebURL(target) {
            return ResearchDocumentTypedLink(
                kind: "url", targetRef: target, label: label
            )
        }
        if let target = value(match, group: 8, in: text),
           isSafeWebURL(target) {
            return ResearchDocumentTypedLink(
                kind: "url", targetRef: target, label: target
            )
        }
        let label = value(match, group: 6, in: text)
        let target = value(match, group: 7, in: text)
            ?? value(match, group: 9, in: text)
        guard let target, isSafeRelativeFilePath(target) else { return nil }
        return ResearchDocumentTypedLink(
            kind: "file", targetRef: target,
            label: label ?? target
        )
    }

    private static func value(
        _ match: NSTextCheckingResult, group: Int, in text: String
    ) -> String? {
        guard match.range(at: group).location != NSNotFound,
              let range = Range(match.range(at: group), in: text) else {
            return nil
        }
        return String(text[range])
    }

    static func isSafeRelativeFilePath(_ value: String) -> Bool {
        let decoded = value.removingPercentEncoding ?? value
        guard !decoded.isEmpty, decoded.utf8.count <= 1_024,
              !decoded.hasPrefix("/"), !decoded.hasPrefix("~"),
              !decoded.contains("\\") else { return false }
        let components = decoded.split(separator: "/", omittingEmptySubsequences: false)
        return components.count > 1 && components.allSatisfy {
            !$0.isEmpty && $0 != "." && $0 != ".."
        }
    }

    static func isSafeWebURL(_ value: String) -> Bool {
        guard value.utf8.count <= 4_096, let url = URL(string: value),
              ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              url.host?.isEmpty == false, url.user == nil, url.password == nil else {
            return false
        }
        return true
    }

    static func reference(from url: URL) -> ResearchDocumentTypedLink? {
        guard url.scheme == "factortester",
              let kind = url.host,
              url.pathComponents.count == 2,
              let target = url.pathComponents.last?.removingPercentEncoding,
              !target.isEmpty
        else { return nil }
        return ResearchDocumentTypedLink(
            kind: kind,
            targetRef: target,
            label: target
        )
    }

    static func renderedText(_ text: String) -> Text {
        segments(in: text).reduce(Text("")) { partial, segment in
            switch segment {
            case let .text(value):
                return partial + Text(ResearchDocumentInlineTextStyle.markdown(value))
            case let .reference(reference):
                var link = AttributedString(" \(reference.label)")
                link.link = reference.url
                link.foregroundColor = ResearchDocumentTypedLinkPresentation.color(
                    for: reference.kind
                )
                return partial
                    + Text(Image(systemName: ResearchDocumentTypedLinkPresentation.symbol(
                        for: reference.kind
                    )))
                    .foregroundColor(
                        ResearchDocumentTypedLinkPresentation.color(
                            for: reference.kind
                        )
                    )
                    + Text(link)
            }
        }
    }
}

enum ResearchDocumentTypedLinkPresentation {
    enum Tint: Equatable {
        case link
        case factor
        case profile
        case product
    }

    static func title(for kind: String) -> String {
        switch kind {
        case "evidence": return L10n.text("证据")
        case "obligation": return L10n.text("研究义务")
        case "task": return L10n.text("任务")
        case "job": return L10n.text("测试任务")
        case "claim": return L10n.text("研究主张")
        case "artifact": return L10n.text("任务生成物")
        case "report_requirement": return L10n.text("报告要求")
        case "trial_plan": return L10n.text("试验计划")
        case "graph_reference": return L10n.text("研究图对象")
        case "checkpoint": return L10n.text("研究记录")
        case "run": return L10n.text("运行")
        case "run_spec": return L10n.text("运行配置")
        case "delta": return L10n.text("状态变化")
        case "factor": return L10n.text("因子")
        case "factor_family": return L10n.text("因子家族")
        case "profile": return L10n.text("Profile")
        case "product": return L10n.text("产品")
        case "contract": return L10n.text("合约")
        case "continuous_contract": return L10n.text("连续合约")
        case "file": return L10n.text("研究文件")
        case "url": return L10n.text("网页链接")
        default: return L10n.text("引用对象")
        }
    }

    static func symbol(for kind: String) -> String {
        switch kind {
        case "evidence": return "doc.text.magnifyingglass"
        case "obligation": return "checkmark.seal"
        case "task", "job": return "checklist"
        case "claim": return "quote.bubble"
        case "artifact": return "paperclip"
        case "trial_plan", "report_requirement": return "list.bullet.clipboard"
        case "graph_reference": return "point.3.connected.trianglepath.dotted"
        case "checkpoint": return "flag"
        case "run": return "play.circle"
        case "run_spec": return "slider.horizontal.3"
        case "delta": return "arrow.left.arrow.right"
        case "factor": return "function"
        case "factor_family": return "square.stack.3d.up"
        case "profile": return "person.crop.rectangle.stack"
        case "product": return "shippingbox"
        case "contract": return "doc.text"
        case "continuous_contract": return "chart.line.uptrend.xyaxis"
        case "file": return "doc.text"
        case "url": return "safari"
        default: return "link"
        }
    }

    static func tint(for kind: String) -> Tint {
        switch kind {
        case "factor", "factor_family": return .factor
        case "profile": return .profile
        case "product", "contract", "continuous_contract": return .product
        default: return .link
        }
    }

    static func color(for kind: String) -> Color {
        switch tint(for: kind) {
        case .factor: return .purple
        case .profile: return .indigo
        case .product: return .teal
        case .link: return .accentColor
        }
    }

    #if os(macOS)
    static func nsColor(for kind: String) -> NSColor {
        switch tint(for: kind) {
        case .factor: return .systemPurple
        case .profile: return .systemIndigo
        case .product: return .systemTeal
        case .link: return .controlAccentColor
        }
    }
    #endif
}
