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

enum ResearchDocumentLinkBoundarySpacing {
    static let value = "\u{2009}"

    static func needsLeadingSpace(
        in segments: [ResearchDocumentTypedLinkParser.Segment],
        at index: Int
    ) -> Bool {
        guard index > segments.startIndex else { return false }
        switch segments[segments.index(before: index)] {
        case let .text(value):
            return value.last.map { !$0.isWhitespace } ?? false
        case .reference:
            return true
        }
    }

    static func needsTrailingSpace(
        in segments: [ResearchDocumentTypedLinkParser.Segment],
        at index: Int
    ) -> Bool {
        let next = segments.index(after: index)
        guard next < segments.endIndex else { return false }
        switch segments[next] {
        case let .text(value):
            return value.first.map { !$0.isWhitespace } ?? false
        case .reference:
            return false
        }
    }
}

extension ResearchDocumentTypedLinkParser {
    static func renderedText(
        _ text: String,
        scope: ResearchDocumentReferenceScope
    ) -> Text {
        let segments = scope.presentationSegments(in: text)
        return segments.indices.reduce(Text("")) { partial, index in
            let segment = segments[index]
            switch segment {
            case let .text(value):
                return partial + Text(ResearchDocumentInlineTextStyle.markdown(value))
            case let .reference(reference):
                var link = AttributedString(" \(reference.label)")
                link.link = reference.url
                link.foregroundColor = ResearchDocumentTypedLinkPresentation.color(
                    for: reference.kind
                )
                let leading = ResearchDocumentLinkBoundarySpacing.needsLeadingSpace(
                    in: segments,
                    at: index
                ) ? Text(ResearchDocumentLinkBoundarySpacing.value) : Text("")
                let trailing = ResearchDocumentLinkBoundarySpacing.needsTrailingSpace(
                    in: segments,
                    at: index
                ) ? Text(ResearchDocumentLinkBoundarySpacing.value) : Text("")
                return partial
                    + leading
                    + Text(Image(systemName: ResearchDocumentTypedLinkPresentation.symbol(
                        for: reference.kind
                    )))
                    .foregroundColor(
                        ResearchDocumentTypedLinkPresentation.color(
                            for: reference.kind
                        )
                    )
                    + Text(link)
                    + trailing
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
