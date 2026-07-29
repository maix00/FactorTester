import Foundation
import SwiftUI

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

    private static let expression = try! NSRegularExpression(
        pattern: #"(?<!\\)\[([^\]\r\n]{1,256})\]\(factortester://([a-z_]+)/([^()\s]+)\)"#
    )

    static func segments(in text: String) -> [Segment] {
        let range = NSRange(text.startIndex..., in: text)
        var cursor = text.startIndex
        var result: [Segment] = []
        for match in expression.matches(in: text, range: range) {
            guard let whole = Range(match.range, in: text),
                  let labelRange = Range(match.range(at: 1), in: text),
                  let kindRange = Range(match.range(at: 2), in: text),
                  let targetRange = Range(match.range(at: 3), in: text)
            else { continue }
            if cursor < whole.lowerBound {
                result.append(.text(String(text[cursor..<whole.lowerBound])))
            }
            let target = String(text[targetRange]).removingPercentEncoding
                ?? String(text[targetRange])
            result.append(.reference(ResearchDocumentTypedLink(
                kind: String(text[kindRange]), targetRef: target,
                label: String(text[labelRange])
            )))
            cursor = whole.upperBound
        }
        if cursor < text.endIndex { result.append(.text(String(text[cursor...]))) }
        return result.isEmpty ? [.text(text)] : result
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

    static func attributedText(_ text: String) -> AttributedString {
        segments(in: text).reduce(AttributedString()) { partial, segment in
            var result = partial
            switch segment {
            case let .text(value):
                result += ResearchDocumentInlineTextStyle.markdown(value)
            case let .reference(reference):
                var link = AttributedString(
                    "\(ResearchDocumentTypedLinkPresentation.glyph(for: reference.kind)) \(reference.label)"
                )
                link.link = reference.url
                link.foregroundColor = .accentColor
                link.underlineStyle = .single
                result += link
            }
            return result
        }
    }
}

enum ResearchDocumentTypedLinkPresentation {
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
        default: return "link"
        }
    }

    static func glyph(for kind: String) -> String {
        switch kind {
        case "evidence": return "⌕"
        case "obligation": return "✓"
        case "task", "job": return "☑"
        case "claim": return "❝"
        case "artifact": return "⌇"
        case "report_requirement", "trial_plan": return "☷"
        case "graph_reference": return "⌘"
        case "checkpoint": return "⚑"
        case "run": return "▷"
        case "run_spec": return "≡"
        case "delta": return "↔"
        default: return "↗"
        }
    }
}

enum ResearchDocumentHTMLRichText {
    static let renderer = #"""
    window.ftAppendResearchRichText=function(root,source){
      function plain(value){var parts=String(value).split('`');for(var i=0;i<parts.length;i++){var paired=(i%2===1)&&(i<parts.length-1),node=paired?document.createElement('code'):document.createTextNode('');if(paired){node.textContent=parts[i];}else{node.nodeValue=(i%2===1?'`':'')+parts[i];}root.appendChild(node);}}
      var pattern=/\[([^\]\r\n]{1,256})\]\(([^()\s]+)\)/g,cursor=0,match;
      while((match=pattern.exec(String(source)))!==null){plain(String(source).slice(cursor,match.index));var label=match[1],target=match[2];if(target.indexOf('factortester://')===0){var parts=target.slice(16).split('/');if(parts.length===2){var reference=document.createElement('span'),icon=document.createElement('span');reference.className='ft-reference';icon.className='ft-reference-icon';icon.textContent=window.ftReferenceIcon(parts[0]);reference.appendChild(icon);reference.appendChild(document.createTextNode(' '+label));root.appendChild(reference);}else{plain(match[0]);}}else if(/^https?:\/\//.test(target)){var link=document.createElement('a');link.href=target;link.textContent=label;root.appendChild(link);}else{plain(match[0]);}cursor=pattern.lastIndex;}plain(String(source).slice(cursor));
    };
    window.ftReferenceIcon=function(kind){return({evidence:'⌕',obligation:'✓',task:'☑',job:'☑',claim:'❝',artifact:'⌇',report_requirement:'☷',trial_plan:'☷',graph_reference:'⌘',checkpoint:'⚑',run:'▷',run_spec:'≡',delta:'↔'})[kind]||'↗';};
    """#
}
