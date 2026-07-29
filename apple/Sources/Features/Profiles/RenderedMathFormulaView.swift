import SwiftUI
import WebKit

struct RenderedMathFormulaView: View {
    let latex: String
    let fallback: String

    @State private var contentHeight: CGFloat = 72

    var body: some View {
        MathFormulaWebView(
            latex: latex,
            fallback: fallback,
            richText: nil,
            openReference: nil,
            contentHeight: $contentHeight
        )
        .frame(maxWidth: .infinity)
        .frame(height: min(max(contentHeight, 48), 420))
        .clipShape(RoundedRectangle(cornerRadius: 7))
        .accessibilityLabel(fallback)
    }
}

struct RenderedInlineMathTextView: View {
    let text: String
    @Environment(\.researchDocumentReferenceAction) private var openReference
    @State private var contentHeight: CGFloat = 36

    var body: some View {
        MathFormulaWebView(
            latex: "",
            fallback: text,
            richText: ResearchReportTextProjection.mathJaxSource(text),
            openReference: openReference,
            contentHeight: $contentHeight
        )
        .frame(maxWidth: .infinity)
        .frame(height: min(max(contentHeight, 28), 420))
        .accessibilityLabel(text)
    }
}

enum MathFormulaDocument {
    static let resourceName = "mathjax-tex-svg"

    static func bootstrapScript(latex: String, fallback: String) -> String {
        let data = try? JSONSerialization.data(
            withJSONObject: [latex, fallback],
            options: []
        )
        let payload = data.flatMap { String(data: $0, encoding: .utf8) }
            ?? #"["","因子公式"]"#
        return "window.ftFormulaPayload=\(payload);"
    }

    static func makeHTML(latex: String, fallback: String) -> String? {
        guard BundledMathJaxRuntime.baseURL != nil else { return nil }
        let payload = bootstrapScript(latex: latex, fallback: fallback)
        return """
        <!doctype html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
        :root{color-scheme:light dark}html,body{margin:0;padding:0;background:transparent}
        body{color:CanvasText;font:-apple-system-body;overflow:hidden}
        #formula{box-sizing:border-box;width:100%;padding:12px 14px;overflow-x:auto;text-align:center;visibility:hidden}
        #formula mjx-container{margin:0!important;max-width:100%}#formula svg{max-width:100%;height:auto}
        #fallback{display:none;box-sizing:border-box;width:100%;padding:12px 14px;color:GrayText}
        </style><script>
        \(payload)
        function ftReportHeight(){requestAnimationFrame(function(){requestAnimationFrame(function(){window.webkit.messageHandlers.formulaHeight.postMessage(Math.ceil(document.documentElement.scrollHeight));});});}
        function ftShowFallback(){document.getElementById('formula').style.display='none';document.getElementById('fallback').style.display='block';ftReportHeight();}
        window.MathJax={tex:{processEscapes:true},svg:{fontCache:'local'},startup:{pageReady:function(){return MathJax.startup.defaultPageReady().then(function(){document.getElementById('formula').style.visibility='visible';ftReportHeight();}).catch(ftShowFallback);}}};
        </script><script src="\(BundledMathJaxRuntime.scriptFilename)"></script></head><body>
        <div id="formula"></div><div id="fallback"></div><script>
        document.getElementById('formula').textContent='\\\\['+window.ftFormulaPayload[0]+'\\\\]';
        document.getElementById('fallback').textContent=window.ftFormulaPayload[1];
        </script></body></html>
        """
    }
}

enum BundledMathJaxRuntime {
    static let scriptFilename = "\(MathFormulaDocument.resourceName).js"

    static let baseURL: URL? = {
        Bundle.main.url(
            forResource: MathFormulaDocument.resourceName,
            withExtension: "js"
        )?.deletingLastPathComponent()
    }()
}

#if os(macOS)
private struct MathFormulaWebView: NSViewRepresentable {
    let latex: String
    let fallback: String
    let richText: String?
    let openReference: ((ResearchDocumentTypedLink) -> Void)?
    @Binding var contentHeight: CGFloat

    func makeCoordinator() -> MathFormulaCoordinator {
        MathFormulaCoordinator(
            contentHeight: $contentHeight,
            openReference: openReference
        )
    }

    func makeNSView(context: Context) -> WKWebView {
        makeWebView(context: context)
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        context.coordinator.openReference = openReference
        load(webView, coordinator: context.coordinator)
    }

    static func dismantleNSView(
        _ webView: WKWebView,
        coordinator: MathFormulaCoordinator
    ) {
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: "formulaHeight"
        )
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: ResearchDocumentWebReferenceMessage.handlerName
        )
    }

    private func makeWebView(context: Context) -> WKWebView {
        let controller = WKUserContentController()
        controller.add(context.coordinator, name: "formulaHeight")
        if openReference != nil {
            controller.add(
                context.coordinator,
                name: ResearchDocumentWebReferenceMessage.handlerName
            )
        }
        let configuration = WKWebViewConfiguration()
        configuration.userContentController = controller
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.underPageBackgroundColor = .clear
        webView.setValue(false, forKey: "drawsBackground")
        webView.enclosingScrollView?.drawsBackground = false
        webView.enclosingScrollView?.hasVerticalScroller = false
        webView.enclosingScrollView?.hasHorizontalScroller = false
        load(webView, coordinator: context.coordinator)
        return webView
    }

    private func load(
        _ webView: WKWebView,
        coordinator: MathFormulaCoordinator
    ) {
        let key = richText ?? latex
        guard coordinator.loadedLatex != key else { return }
        coordinator.loadedLatex = key
        loadDocument(
            webView,
            latex: latex,
            fallback: fallback,
            richText: richText
        )
    }
}
#else
private struct MathFormulaWebView: UIViewRepresentable {
    let latex: String
    let fallback: String
    let richText: String?
    let openReference: ((ResearchDocumentTypedLink) -> Void)?
    @Binding var contentHeight: CGFloat

    func makeCoordinator() -> MathFormulaCoordinator {
        MathFormulaCoordinator(
            contentHeight: $contentHeight,
            openReference: openReference
        )
    }

    func makeUIView(context: Context) -> WKWebView {
        let controller = WKUserContentController()
        controller.add(context.coordinator, name: "formulaHeight")
        if openReference != nil {
            controller.add(
                context.coordinator,
                name: ResearchDocumentWebReferenceMessage.handlerName
            )
        }
        let configuration = WKWebViewConfiguration()
        configuration.userContentController = controller
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.isScrollEnabled = false
        load(webView, coordinator: context.coordinator)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.openReference = openReference
        load(webView, coordinator: context.coordinator)
    }

    static func dismantleUIView(
        _ webView: WKWebView,
        coordinator: MathFormulaCoordinator
    ) {
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: "formulaHeight"
        )
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: ResearchDocumentWebReferenceMessage.handlerName
        )
    }

    private func load(
        _ webView: WKWebView,
        coordinator: MathFormulaCoordinator
    ) {
        let key = richText ?? latex
        guard coordinator.loadedLatex != key else { return }
        coordinator.loadedLatex = key
        loadDocument(
            webView,
            latex: latex,
            fallback: fallback,
            richText: richText
        )
    }
}
#endif

private final class MathFormulaCoordinator: NSObject, WKScriptMessageHandler {
    @Binding var contentHeight: CGFloat
    var loadedLatex = ""
    var openReference: ((ResearchDocumentTypedLink) -> Void)?

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
           let reference = ResearchDocumentWebReferenceMessage.decode(
               message.body
           ) {
            DispatchQueue.main.async { [weak self] in
                self?.openReference?(reference)
            }
            return
        }
        guard message.name == "formulaHeight",
              let value = message.body as? NSNumber else { return }
        let height = CGFloat(truncating: value)
        guard height.isFinite, height > 0 else { return }
        DispatchQueue.main.async { [weak self] in
            self?.contentHeight = height
        }
    }
}

private func loadDocument(
    _ webView: WKWebView,
    latex: String,
    fallback: String,
    richText: String? = nil
) {
    let html = richText.flatMap(MathRichTextDocument.makeHTML)
        ?? MathFormulaDocument.makeHTML(latex: latex, fallback: fallback)
    guard let html else {
        webView.loadHTMLString(
            "<html><body>\(fallback)</body></html>",
            baseURL: nil
        )
        return
    }
    let controller = webView.configuration.userContentController
    controller.removeAllUserScripts()
    webView.loadHTMLString(html, baseURL: BundledMathJaxRuntime.baseURL)
}

enum MathRichTextDocument {
    static func makeHTML(_ text: String) -> String? {
        guard BundledMathJaxRuntime.baseURL != nil else { return nil }
        let data = try? JSONSerialization.data(
            withJSONObject: [text],
            options: []
        )
        let payload = data.flatMap { String(data: $0, encoding: .utf8) }
            ?? #"[""]"#
        return """
        <!doctype html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
        :root{color-scheme:light dark}html,body{margin:0;padding:0;background:transparent}
        body{color:CanvasText;font:-apple-system-body;line-height:1.55;overflow:hidden}
        #content{box-sizing:border-box;width:100%;padding:0;visibility:hidden}
        #content mjx-container{margin:0 .08em!important;display:inline!important}
        #content code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;padding:.08em .28em;border-radius:4px;background:color-mix(in srgb,CanvasText 8%,transparent)}
        .ft-reference,a{color:LinkText;text-decoration:underline;cursor:pointer}.ft-reference-icon{font-weight:600}
        #fallback{display:none;color:GrayText}
        </style><script>
        window.ftRichText=\(payload)[0];
        function ftHeight(){requestAnimationFrame(function(){requestAnimationFrame(function(){window.webkit.messageHandlers.formulaHeight.postMessage(Math.ceil(document.documentElement.scrollHeight));});});}
        function ftFallback(){document.getElementById('content').style.display='none';document.getElementById('fallback').style.display='block';ftHeight();}
        window.MathJax={tex:{processEscapes:true,inlineMath:[['\\\\(','\\\\)']],displayMath:[['\\\\[','\\\\]'],['$$','$$']]},options:{ignoreHtmlClass:'ft-reference'},svg:{fontCache:'local'},startup:{pageReady:function(){return MathJax.startup.defaultPageReady().then(function(){document.getElementById('content').style.visibility='visible';ftHeight();}).catch(ftFallback);}}};
        \(ResearchDocumentHTMLRichText.renderer)
        </script><script src="\(BundledMathJaxRuntime.scriptFilename)"></script></head><body>
        <div id="content"></div><div id="fallback"></div><script>
        window.ftAppendResearchRichText(document.getElementById('content'),window.ftRichText);
        document.getElementById('fallback').textContent=window.ftRichText;
        </script></body></html>
        """
    }
}
