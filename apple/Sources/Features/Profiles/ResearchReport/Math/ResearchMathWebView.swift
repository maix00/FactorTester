import SwiftUI
import WebKit

enum ResearchMathWebScrollPolicy: Equatable {
    case contained
    case displayFormula
}

final class ResearchMathWebCoordinator: NSObject, WKScriptMessageHandler {
    @Binding var contentHeight: CGFloat
    var loadedKey = ""
    var openReference: ((ResearchDocumentTypedLink) -> Void)?
    var updateContentMetrics: ((CGFloat, Bool) -> Void)?

    init(
        contentHeight: Binding<CGFloat>,
        openReference: ((ResearchDocumentTypedLink) -> Void)?
    ) {
        _contentHeight = contentHeight
        self.openReference = openReference
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        if message.name == ResearchDocumentWebReferenceMessage.handlerName,
           let reference = ResearchDocumentWebReferenceMessage.decode(message.body) {
            DispatchQueue.main.async { [weak self] in
                self?.openReference?(reference)
            }
            return
        }
        guard message.name == ResearchMathRuntime.heightHandlerName,
              let metrics = message.body as? [String: Any],
              let value = metrics["height"] as? NSNumber else { return }
        let height = CGFloat(truncating: value)
        guard height.isFinite, height > 0 else { return }
        let horizontalOverflow = (metrics["horizontalOverflow"] as? NSNumber)?
            .boolValue ?? false
        DispatchQueue.main.async { [weak self] in
            self?.contentHeight = height
            self?.updateContentMetrics?(height, horizontalOverflow)
        }
    }

}

enum ResearchMathWebConfiguration {
    static func make(
        coordinator: ResearchMathWebCoordinator,
        acceptsReferences: Bool
    ) -> WKWebViewConfiguration {
        let controller = WKUserContentController()
        controller.add(coordinator, name: ResearchMathRuntime.heightHandlerName)
        if acceptsReferences {
            controller.add(
                coordinator,
                name: ResearchDocumentWebReferenceMessage.handlerName
            )
        }
        let configuration = WKWebViewConfiguration()
        configuration.userContentController = controller
        return configuration
    }

    static func load(
        _ document: ResearchMathWebDocument,
        into webView: WKWebView,
        coordinator: ResearchMathWebCoordinator
    ) {
        guard coordinator.loadedKey != document.key else { return }
        coordinator.loadedKey = document.key
        webView.loadHTMLString(document.html, baseURL: document.baseURL)
    }

    static func dismantle(_ webView: WKWebView) {
        let controller = webView.configuration.userContentController
        controller.removeScriptMessageHandler(
            forName: ResearchMathRuntime.heightHandlerName
        )
        controller.removeScriptMessageHandler(
            forName: ResearchDocumentWebReferenceMessage.handlerName
        )
    }
}

#if os(macOS)
typealias ResearchMathWebView = ResearchMathWebViewMac
#else
typealias ResearchMathWebView = ResearchMathWebViewIOS
#endif
