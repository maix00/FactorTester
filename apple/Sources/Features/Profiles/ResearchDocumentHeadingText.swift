import SwiftUI

struct ResearchDocumentHeadingText: View {
    let text: String
    let font: Font
    let componentID: String

    @Environment(\.researchDocumentReferenceAction) private var openReference
    @Environment(\.researchDocumentReferenceBindings) private var bindings

    var body: some View {
        ResearchDocumentTypedLinkParser.renderedText(text, scope: referenceScope)
            .font(font)
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
    }

    private var referenceScope: ResearchDocumentReferenceScope {
        .init(componentID: componentID, bindings: bindings)
    }
}
