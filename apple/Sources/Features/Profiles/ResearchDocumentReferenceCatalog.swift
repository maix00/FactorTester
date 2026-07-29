import Foundation
import SwiftUI
#if os(macOS)
import AppKit
#endif

enum ResearchDocumentReferenceTint: String, Equatable {
    case link
    case evidence
    case factor
    case profile
    case product
}

struct ResearchDocumentReferenceDescriptor: Equatable {
    let kind: String
    let titleKey: String
    let symbol: String
    let tint: ResearchDocumentReferenceTint
    let webIcon: String
}

enum ResearchDocumentReferenceCatalog {
    private static let descriptors: [String: ResearchDocumentReferenceDescriptor] = [
        "evidence": item("evidence", "证据", "doc.text.magnifyingglass", .evidence, "⌕"),
        "obligation": item("obligation", "研究义务", "checkmark.seal", .link, "✓"),
        "task": item("task", "任务", "checklist", .link, "☑"),
        "job": item("job", "测试任务", "checklist", .link, "☑"),
        "claim": item("claim", "研究主张", "quote.bubble", .link, "❝"),
        "artifact": item("artifact", "任务生成物", "paperclip", .link, "⌇"),
        "report_requirement": item(
            "report_requirement", "报告要求", "list.bullet.clipboard", .link, "☷"
        ),
        "trial_plan": item("trial_plan", "试验计划", "list.bullet.clipboard", .link, "☷"),
        "graph_reference": item(
            "graph_reference", "研究图对象",
            "point.3.connected.trianglepath.dotted", .link, "⌘"
        ),
        "checkpoint": item("checkpoint", "研究记录", "flag", .link, "⚑"),
        "run": item("run", "运行", "play.circle", .link, "▷"),
        "run_spec": item("run_spec", "运行配置", "slider.horizontal.3", .link, "≡"),
        "delta": item("delta", "状态变化", "arrow.left.arrow.right", .link, "↔"),
        "factor": item("factor", "因子", "function", .factor, "ƒ"),
        "factor_family": item(
            "factor_family", "因子家族", "square.stack.3d.up", .factor, "ƒ"
        ),
        "profile": item(
            "profile", "Profile", "person.crop.rectangle.stack", .profile, "♙"
        ),
        "profile_revision": item(
            "profile_revision", "Profile 版本",
            "person.crop.rectangle.stack", .profile, "♙"
        ),
        "product": item("product", "产品", "shippingbox", .product, "◇"),
        "contract": item("contract", "合约", "doc.text", .product, "▤"),
        "continuous_contract": item(
            "continuous_contract", "连续合约",
            "chart.line.uptrend.xyaxis", .product, "∿"
        ),
        "file": item("file", "研究文件", "doc.text", .link, "⌇"),
        "url": item("url", "网页链接", "safari", .link, "↗"),
    ]

    static func descriptor(for kind: String) -> ResearchDocumentReferenceDescriptor {
        descriptors[kind] ?? item(kind, "引用对象", "link", .link, "↗")
    }

    static func contains(_ kind: String) -> Bool {
        descriptors[kind] != nil
    }

    static func title(for kind: String) -> String {
        L10n.text(descriptor(for: kind).titleKey)
    }

    static func color(for kind: String) -> Color {
        switch descriptor(for: kind).tint {
        case .evidence: return .blue
        case .factor: return .purple
        case .profile: return .indigo
        case .product: return .teal
        case .link: return .accentColor
        }
    }

    #if os(macOS)
    static func nsColor(for kind: String) -> NSColor {
        switch descriptor(for: kind).tint {
        case .evidence: return .systemBlue
        case .factor: return .systemPurple
        case .profile: return .systemIndigo
        case .product: return .systemTeal
        case .link: return .controlAccentColor
        }
    }
    #endif

    static var webBootstrap: String {
        let payload = descriptors.mapValues {
            ["icon": $0.webIcon, "tone": $0.tint.rawValue]
        }
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(
                withJSONObject: payload, options: [.sortedKeys]
              ),
              let json = String(data: data, encoding: .utf8) else {
            return "window.ftReferencePresentation={};"
        }
        return "window.ftReferencePresentation=\(json);"
    }

    static let webCSS = """
    :root{--ft-ref-evidence:rgb(0 122 255);--ft-ref-factor:rgb(175 82 222);
      --ft-ref-profile:rgb(88 86 214);--ft-ref-product:rgb(48 176 199)}
    @media(prefers-color-scheme:dark){:root{--ft-ref-evidence:rgb(10 132 255);
      --ft-ref-factor:rgb(191 90 242);--ft-ref-profile:rgb(94 92 230);
      --ft-ref-product:rgb(64 200 224)}}
    .ft-reference[data-reference-tone="evidence"]{color:var(--ft-ref-evidence)}
    .ft-reference[data-reference-tone="factor"]{color:var(--ft-ref-factor)}
    .ft-reference[data-reference-tone="profile"]{color:var(--ft-ref-profile)}
    .ft-reference[data-reference-tone="product"]{color:var(--ft-ref-product)}
    """

    private static func item(
        _ kind: String,
        _ titleKey: String,
        _ symbol: String,
        _ tint: ResearchDocumentReferenceTint,
        _ webIcon: String
    ) -> ResearchDocumentReferenceDescriptor {
        .init(
            kind: kind, titleKey: titleKey, symbol: symbol,
            tint: tint, webIcon: webIcon
        )
    }
}
