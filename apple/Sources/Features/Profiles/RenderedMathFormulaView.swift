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
    @State private var contentHeight: CGFloat = 36

    var body: some View {
        MathFormulaWebView(
            latex: "",
            fallback: text,
            richText: ResearchReportTextProjection.mathJaxSource(text),
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
        guard let runtime = BundledMathJaxRuntime.source else { return nil }
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
        </script><script>\(runtime)</script></head><body>
        <div id="formula"></div><div id="fallback"></div><script>
        document.getElementById('formula').textContent='\\\\['+window.ftFormulaPayload[0]+'\\\\]';
        document.getElementById('fallback').textContent=window.ftFormulaPayload[1];
        </script></body></html>
        """
    }
}

private enum BundledMathJaxRuntime {
    static let source: String? = {
        guard let url = Bundle.main.url(
            forResource: MathFormulaDocument.resourceName,
            withExtension: "js"
        ) else { return nil }
        return try? String(contentsOf: url, encoding: .utf8)
    }()
}

#if os(macOS)
private struct MathFormulaWebView: NSViewRepresentable {
    let latex: String
    let fallback: String
    let richText: String?
    @Binding var contentHeight: CGFloat

    func makeCoordinator() -> MathFormulaCoordinator {
        MathFormulaCoordinator(contentHeight: $contentHeight)
    }

    func makeNSView(context: Context) -> WKWebView {
        makeWebView(context: context)
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        load(webView, coordinator: context.coordinator)
    }

    static func dismantleNSView(
        _ webView: WKWebView,
        coordinator: MathFormulaCoordinator
    ) {
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: "formulaHeight"
        )
    }

    private func makeWebView(context: Context) -> WKWebView {
        let controller = WKUserContentController()
        controller.add(context.coordinator, name: "formulaHeight")
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
    @Binding var contentHeight: CGFloat

    func makeCoordinator() -> MathFormulaCoordinator {
        MathFormulaCoordinator(contentHeight: $contentHeight)
    }

    func makeUIView(context: Context) -> WKWebView {
        let controller = WKUserContentController()
        controller.add(context.coordinator, name: "formulaHeight")
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
        load(webView, coordinator: context.coordinator)
    }

    static func dismantleUIView(
        _ webView: WKWebView,
        coordinator: MathFormulaCoordinator
    ) {
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: "formulaHeight"
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

    init(contentHeight: Binding<CGFloat>) {
        _contentHeight = contentHeight
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
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
    webView.loadHTMLString(html, baseURL: nil)
}

enum MathRichTextDocument {
    static func makeHTML(_ text: String) -> String? {
        guard let runtime = BundledMathJaxRuntime.source else { return nil }
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
        #fallback{display:none;color:GrayText}
        </style><script>
        window.ftRichText=\(payload)[0];
        function ftHeight(){requestAnimationFrame(function(){requestAnimationFrame(function(){window.webkit.messageHandlers.formulaHeight.postMessage(Math.ceil(document.documentElement.scrollHeight));});});}
        function ftFallback(){document.getElementById('content').style.display='none';document.getElementById('fallback').style.display='block';ftHeight();}
        window.MathJax={tex:{processEscapes:true,inlineMath:[['\\\\(','\\\\)']]},svg:{fontCache:'local'},startup:{pageReady:function(){return MathJax.startup.defaultPageReady().then(function(){document.getElementById('content').style.visibility='visible';ftHeight();}).catch(ftFallback);}}};
        </script><script>\(runtime)</script></head><body>
        <div id="content"></div><div id="fallback"></div><script>
        (function(){
          var root=document.getElementById('content'),parts=window.ftRichText.split('`');
          for(var i=0;i<parts.length;i++){
            var paired=(i%2===1)&&(i<parts.length-1);
            var node=paired?document.createElement('code'):document.createTextNode('');
            if(paired){node.textContent=parts[i];}else{node.nodeValue=(i%2===1?'`':'')+parts[i];}
            root.appendChild(node);
          }
        })();
        document.getElementById('fallback').textContent=window.ftRichText;
        </script></body></html>
        """
    }
}
