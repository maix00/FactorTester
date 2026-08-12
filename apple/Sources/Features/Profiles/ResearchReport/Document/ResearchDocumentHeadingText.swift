import SwiftUI
#if os(macOS)
import AppKit
#endif

enum ResearchDocumentHeadingRole {
    case chapter
    case section
    case component

    var swiftUIFont: Font {
        switch self {
        case .chapter: return .title2.weight(.semibold)
        case .section: return .headline
        case .component: return .subheadline.weight(.semibold)
        }
    }

    #if os(macOS)
    var nsFont: NSFont {
        let style: NSFont.TextStyle
        switch self {
        case .chapter: style = .title2
        case .section: style = .headline
        case .component: style = .subheadline
        }
        let preferred = NSFont.preferredFont(forTextStyle: style)
        guard self == .chapter else { return preferred }
        return NSFont.systemFont(
            ofSize: preferred.pointSize,
            weight: .semibold
        )
    }
    #endif
}

struct ResearchDocumentHeadingText: View {
    let text: String
    let role: ResearchDocumentHeadingRole
    let componentID: String
    var onPlainClick: (() -> Void)? = nil

    @Environment(\.researchDocumentReferenceAction) private var openReference
    @Environment(\.researchDocumentReferenceBindings) private var bindings

    var body: some View {
        #if os(macOS)
        ResearchDocumentInlineTextMac(
            text: text,
            referenceScope: referenceScope,
            font: role.nsFont,
            openReference: openLocatedReference,
            onPlainClick: onPlainClick
        )
        #else
        ResearchDocumentTypedLinkParser.renderedText(text, scope: referenceScope)
            .font(role.swiftUIFont)
            .environment(\.openURL, OpenURLAction { url in
                guard let reference = ResearchDocumentTypedLinkParser.reference(
                    from: url, preservingLabelIn: text
                ), let trusted = referenceScope.trusted(reference) else {
                    return .systemAction
                }
                openReference(trusted)
                return .handled
            })
            .textSelection(.enabled)
        #endif
    }

    private func openLocatedReference(
        _ reference: ResearchDocumentTypedLink
    ) {
        guard let trusted = referenceScope.trusted(reference) else { return }
        openReference(trusted)
    }

    private var referenceScope: ResearchDocumentReferenceScope {
        .init(componentID: componentID, bindings: bindings)
    }
}
