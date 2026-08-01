#if !os(macOS)
import SwiftUI
import WebKit

struct ResearchMathWebViewIOS: UIViewRepresentable {
    let document: ResearchMathWebDocument
    let openReference: ((ResearchDocumentTypedLink) -> Void)?
    @Binding var contentHeight: CGFloat

    func makeCoordinator() -> ResearchMathWebCoordinator {
        ResearchMathWebCoordinator(
            contentHeight: $contentHeight,
            openReference: openReference
        )
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = ResearchMathWebConfiguration.make(
            coordinator: context.coordinator,
            acceptsReferences: openReference != nil
        )
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.isScrollEnabled = false
        ResearchMathWebConfiguration.load(
            document,
            into: webView,
            coordinator: context.coordinator
        )
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.openReference = openReference
        ResearchMathWebConfiguration.load(
            document,
            into: webView,
            coordinator: context.coordinator
        )
    }

    static func dismantleUIView(
        _ webView: WKWebView,
        coordinator: ResearchMathWebCoordinator
    ) {
        ResearchMathWebConfiguration.dismantle(webView)
    }
}
#endif
