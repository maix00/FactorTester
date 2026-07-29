import Foundation
import SwiftUI
#if os(macOS)
import AppKit
#endif

struct ResearchDocumentTypedLink: Equatable, Hashable, Identifiable {
    let kind: String
    let targetRef: String
    let label: String
    let componentID: String?

    init(
        kind: String,
        targetRef: String,
        label: String,
        componentID: String? = nil
    ) {
        self.kind = kind
        self.targetRef = targetRef
        self.label = label
        self.componentID = componentID
    }

    var id: String {
        "\(componentID ?? "")\u{1f}\(kind)\u{1f}\(targetRef)\u{1f}\(label)"
    }

    var url: URL? {
        guard let encoded = targetRef.addingPercentEncoding(
            withAllowedCharacters: .alphanumerics
        ) else { return nil }
        return URL(string: "factortester://\(kind)/\(encoded)")
    }

    func located(in componentID: String) -> Self {
        .init(
            kind: kind, targetRef: targetRef, label: label,
            componentID: componentID.isEmpty ? nil : componentID
        )
    }
}

enum ResearchDocumentTypedLinkParser {
    enum Segment: Equatable {
        case text(String)
        case reference(ResearchDocumentTypedLink)
    }
}

extension ResearchDocumentTypedLinkParser {
    static func renderedText(
        _ text: String,
        scope: ResearchDocumentReferenceScope
    ) -> Text {
        scope.presentationSegments(in: text).reduce(Text("")) { partial, segment in
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
    typealias Tint = ResearchDocumentReferenceTint

    static func title(for kind: String) -> String {
        ResearchDocumentReferenceCatalog.title(for: kind)
    }

    static func symbol(for kind: String) -> String {
        ResearchDocumentReferenceCatalog.descriptor(for: kind).symbol
    }

    static func tint(for kind: String) -> Tint {
        ResearchDocumentReferenceCatalog.descriptor(for: kind).tint
    }

    static func color(for kind: String) -> Color {
        ResearchDocumentReferenceCatalog.color(for: kind)
    }

    #if os(macOS)
    static func nsColor(for kind: String) -> NSColor {
        ResearchDocumentReferenceCatalog.nsColor(for: kind)
    }
    #endif
}
