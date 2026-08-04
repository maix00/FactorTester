#if os(macOS)
import AppKit
import SwiftUI
import WebKit

struct ResearchMathWebViewMac: NSViewRepresentable {
    let document: ResearchMathWebDocument
    let openReference: ((ResearchDocumentTypedLink) -> Void)?
    let scrollPolicy: ResearchMathWebScrollPolicy
    @Binding var contentHeight: CGFloat

    func makeCoordinator() -> ResearchMathWebCoordinator {
        ResearchMathWebCoordinator(
            contentHeight: $contentHeight,
            openReference: openReference
        )
    }

    func makeNSView(context: Context) -> ResearchMathWebContentView {
        let configuration = ResearchMathWebConfiguration.make(
            coordinator: context.coordinator,
            acceptsReferences: openReference != nil
        )
        let webView = ResearchMathWebContentView(
            frame: .zero,
            configuration: configuration
        )
        webView.scrollPolicy = scrollPolicy
        context.coordinator.updateContentMetrics = { [weak webView] height, overflow in
            webView?.reportedContentHeight = height
            webView?.hasHorizontalOverflow = overflow
        }
        webView.underPageBackgroundColor = .clear
        webView.setValue(false, forKey: "drawsBackground")
        ResearchMathWebConfiguration.load(
            document,
            into: webView,
            coordinator: context.coordinator
        )
        return webView
    }

    func updateNSView(_ webView: ResearchMathWebContentView, context: Context) {
        context.coordinator.openReference = openReference
        webView.scrollPolicy = scrollPolicy
        ResearchMathWebConfiguration.load(
            document,
            into: webView,
            coordinator: context.coordinator
        )
    }

    static func dismantleNSView(
        _ webView: ResearchMathWebContentView,
        coordinator: ResearchMathWebCoordinator
    ) {
        coordinator.updateContentMetrics = nil
        ResearchMathWebConfiguration.dismantle(webView)
    }
}

enum ResearchMathWheelDestination: Equatable {
    case outerReport
    case webContent
}

enum ResearchMathWheelRouting {
    static func destination(
        deltaX: CGFloat,
        deltaY: CGFloat,
        hasHorizontalOverflow: Bool,
        hasVerticalOverflow: Bool = false
    ) -> ResearchMathWheelDestination {
        if abs(deltaX) > abs(deltaY) {
            return hasHorizontalOverflow ? .webContent : .outerReport
        }
        return hasVerticalOverflow ? .webContent : .outerReport
    }
}

final class ResearchMathWebContentView: WKWebView {
    var scrollPolicy = ResearchMathWebScrollPolicy.contained
    var hasHorizontalOverflow = false
    var reportedContentHeight: CGFloat = 0

    override func scrollWheel(with event: NSEvent) {
        switch ResearchMathWheelRouting.destination(
            deltaX: event.scrollingDeltaX,
            deltaY: event.scrollingDeltaY,
            hasHorizontalOverflow: hasHorizontalOverflow,
            hasVerticalOverflow: scrollPolicy == .contained
                && reportedContentHeight > bounds.height + 1
        ) {
        case .webContent:
            super.scrollWheel(with: event)
        case .outerReport:
            forwardWheelToOuterScrollView(event)
        }
    }

    private func forwardWheelToOuterScrollView(_ event: NSEvent) {
        var ancestor = superview
        while let view = ancestor {
            if let scrollView = view as? NSScrollView {
                scrollView.scrollWheel(with: event)
                return
            }
            ancestor = view.superview
        }
        nextResponder?.scrollWheel(with: event)
    }
}
#endif
