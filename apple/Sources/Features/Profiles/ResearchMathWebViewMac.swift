#if os(macOS)
import SwiftUI
import WebKit

struct ResearchMathWebViewMac: NSViewRepresentable {
    let document: ResearchMathWebDocument
    let openReference: ((ResearchDocumentTypedLink) -> Void)?
    @Binding var contentHeight: CGFloat

    func makeCoordinator() -> ResearchMathWebCoordinator {
        ResearchMathWebCoordinator(
            contentHeight: $contentHeight,
            openReference: openReference
        )
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = ResearchMathWebConfiguration.make(
            coordinator: context.coordinator,
            acceptsReferences: openReference != nil
        )
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.underPageBackgroundColor = .clear
        webView.setValue(false, forKey: "drawsBackground")
        webView.enclosingScrollView?.drawsBackground = false
        webView.enclosingScrollView?.hasVerticalScroller = false
        webView.enclosingScrollView?.hasHorizontalScroller = false
        ResearchMathWebConfiguration.load(
            document,
            into: webView,
            coordinator: context.coordinator
        )
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        context.coordinator.openReference = openReference
        ResearchMathWebConfiguration.load(
            document,
            into: webView,
            coordinator: context.coordinator
        )
    }

    static func dismantleNSView(
        _ webView: WKWebView,
        coordinator: ResearchMathWebCoordinator
    ) {
        ResearchMathWebConfiguration.dismantle(webView)
    }
}
#endif
