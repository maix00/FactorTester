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
}

enum ResearchDocumentReferenceCatalog {
    private static let descriptors: [String: ResearchDocumentReferenceDescriptor] = [
        "evidence": item("evidence", "证据", "doc.text.magnifyingglass", .evidence),
        "job": item("job", "测试任务", "checklist", .link),
        "artifact": item("artifact", "任务生成物", "paperclip", .link),
        "trial_plan": item("trial_plan", "试验计划", "list.bullet.clipboard", .link),
        "run": item("run", "运行", "play.circle", .link),
        "run_spec": item("run_spec", "运行配置", "slider.horizontal.3", .link),
        "factor": item("factor", "因子", "function", .factor),
        "factor_family": item(
            "factor_family", "因子家族", "function", .factor
        ),
        "factor_set": item(
            "factor_set", "因子集合", "square.stack.3d.up", .factor
        ),
        "profile": item(
            "profile", "Profile", "person.crop.rectangle.stack", .profile
        ),
        "profile_revision": item(
            "profile_revision", "Profile 版本",
            "person.crop.rectangle.stack", .profile
        ),
        "product": item("product", "产品", "shippingbox", .product),
        "product_group": item(
            "product_group", "产品组", "shippingbox.and.arrow.backward", .product
        ),
        "contract": item("contract", "合约", "doc.text", .product),
        "continuous_contract": item(
            "continuous_contract", "连续合约",
            "chart.line.uptrend.xyaxis", .product
        ),
        "file": item("file", "研究文件", "doc.text", .link),
        "url": item("url", "网页链接", "safari", .link),
    ]

    /// Reference kinds have appeared with both JSON-style underscores and
    /// URL-style hyphens.  They identify the same object type and must share
    /// one descriptor, color, icon, and Web tab template.
    static func canonicalKind(_ kind: String) -> String {
        kind.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "-", with: "_")
    }

    static func descriptor(for kind: String) -> ResearchDocumentReferenceDescriptor {
        let canonical = canonicalKind(kind)
        return descriptors[canonical] ?? item(canonical, "引用对象", "link", .link)
    }

    static func contains(_ kind: String) -> Bool {
        descriptors[canonicalKind(kind)] != nil
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
        webBootstrap(forKinds: Set(descriptors.keys))
    }

    static func webBootstrap(for sources: [String]) -> String {
        webBootstrap(forKinds: referencedKinds(in: sources))
    }

    private static func webBootstrap(forKinds kinds: Set<String>) -> String {
        let payload = descriptors.filter {
            kinds.contains($0.key)
        }.mapValues {
            ["symbol": $0.symbol, "tone": $0.tint.rawValue]
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

    static func webIconBootstrap(for sources: [String]) -> String {
        let kinds = referencedKinds(in: sources)
        #if os(macOS)
        let payload: [String: String] = Dictionary(
            uniqueKeysWithValues: kinds.compactMap {
            kind -> (String, String)? in
            guard let icon = ResearchDocumentReferenceSymbolImage.dataURL(
                for: kind
            ) else { return nil }
            return (kind, icon)
        })
        #else
        let payload: [String: String] = [:]
        #endif
        let data = try? JSONSerialization.data(
            withJSONObject: payload,
            options: [.sortedKeys]
        )
        let json = data.flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
        return "window.ftReferenceIcons=\(json);"
    }

    private static func referencedKinds(in sources: [String]) -> Set<String> {
        Set(sources.flatMap { source -> [String] in
            ResearchDocumentTypedLinkParser.segments(in: source).compactMap {
                guard case let .reference(reference) = $0 else { return nil }
                return canonicalKind(reference.kind)
            }
        })
    }

    static let webCSS = """
    :root{--ft-ref-evidence:rgb(0 136 255);--ft-ref-factor:rgb(203 48 224);
      --ft-ref-profile:rgb(97 85 245);--ft-ref-product:rgb(0 195 208)}
    @media(prefers-color-scheme:dark){:root{--ft-ref-evidence:rgb(0 145 255);
      --ft-ref-factor:rgb(219 52 242);--ft-ref-profile:rgb(109 124 255);
      --ft-ref-product:rgb(0 210 224)}}
    .ft-reference[data-reference-tone="evidence"]{color:var(--ft-ref-evidence)}
    .ft-reference[data-reference-tone="factor"]{color:var(--ft-ref-factor)}
    .ft-reference[data-reference-tone="profile"]{color:var(--ft-ref-profile)}
    .ft-reference[data-reference-tone="product"]{color:var(--ft-ref-product)}
    .ft-reference{text-decoration:none}
    """

    private static func item(
        _ kind: String,
        _ titleKey: String,
        _ symbol: String,
        _ tint: ResearchDocumentReferenceTint
    ) -> ResearchDocumentReferenceDescriptor {
        .init(
            kind: kind, titleKey: titleKey, symbol: symbol,
            tint: tint
        )
    }
}
