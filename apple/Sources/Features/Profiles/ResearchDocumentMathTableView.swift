import SwiftUI
import WebKit

/// Formula-heavy tables share one local MathJax document instead of creating
/// a WebView for every visible formula cell. Ordinary tables stay native/lazy.
struct ResearchDocumentMathTableView: View {
    let columns: [String]
    let rows: [[String]]
    let maximumHeight: CGFloat

    @State private var contentHeight: CGFloat = 160

    var body: some View {
        MathTableWebView(
            columns: columns, rows: rows, contentHeight: $contentHeight
        )
        .frame(maxWidth: .infinity)
        .frame(height: min(max(contentHeight, 96), maximumHeight))
        .background(Color.secondary.opacity(0.025), in: RoundedRectangle(cornerRadius: 7))
        .clipShape(RoundedRectangle(cornerRadius: 7))
        .accessibilityLabel(L10n.text("含公式的研究表格"))
    }
}

enum MathTableDocument {
    static func makeHTML(columns: [String], rows: [[String]]) -> String? {
        guard let runtime = BundledMathJaxRuntime.source,
              let data = try? JSONSerialization.data(
                withJSONObject: ["columns": columns, "rows": rows], options: []
              ),
              let payload = String(data: data, encoding: .utf8)
        else { return nil }
        return """
        <!doctype html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
        :root{color-scheme:light dark}html,body{margin:0;background:transparent;height:100%}
        body{color:CanvasText;font:-apple-system-body;overflow:auto}
        table{border-collapse:collapse;min-width:max-content;width:100%}th,td{padding:8px;text-align:left;vertical-align:top;border:1px solid color-mix(in srgb,CanvasText 18%,transparent)}th{position:sticky;top:0;background:Canvas;color:CanvasText;font-weight:600;z-index:1}tr:nth-child(even){background:color-mix(in srgb,CanvasText 3%,transparent)}
        mjx-container{margin:0 .08em!important;display:inline!important}mjx-container svg{max-width:100%;height:auto}th code,td code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;padding:.08em .28em;border-radius:4px;background:color-mix(in srgb,CanvasText 8%,transparent)}
        </style><script>
        window.ftTable=\(payload);
        function ftHeight(){requestAnimationFrame(function(){requestAnimationFrame(function(){window.webkit.messageHandlers.tableHeight.postMessage(Math.ceil(document.documentElement.scrollHeight));});});}
        window.MathJax={tex:{processEscapes:true,inlineMath:[['\\\\(','\\\\)']],displayMath:[['\\\\[','\\\\]'],['$$','$$']]},svg:{fontCache:'local'},startup:{pageReady:function(){return MathJax.startup.defaultPageReady().then(ftHeight).catch(ftHeight);}}};
        </script><script>\(runtime)</script></head><body><table id="table"></table><script>
        (function(){function appendRichText(root,value){var parts=String(value).split('`');for(var i=0;i<parts.length;i++){var paired=(i%2===1)&&(i<parts.length-1),node=paired?document.createElement('code'):document.createTextNode('');if(paired){node.textContent=parts[i];}else{node.nodeValue=(i%2===1?'`':'')+parts[i];}root.appendChild(node);}}var data=window.ftTable,table=document.getElementById('table'),head=document.createElement('thead'),header=document.createElement('tr'),body=document.createElement('tbody');data.columns.forEach(function(value){var cell=document.createElement('th');appendRichText(cell,value);header.appendChild(cell);});head.appendChild(header);data.rows.forEach(function(row){var line=document.createElement('tr');row.forEach(function(value){var cell=document.createElement('td');appendRichText(cell,value);line.appendChild(cell);});body.appendChild(line);});table.appendChild(head);table.appendChild(body);})();
        </script></body></html>
        """
    }
}

private final class MathTableCoordinator: NSObject, WKScriptMessageHandler {
    @Binding var contentHeight: CGFloat
    var loadedKey = ""

    init(contentHeight: Binding<CGFloat>) { _contentHeight = contentHeight }

    func userContentController(
        _ userContentController: WKUserContentController, didReceive message: WKScriptMessage
    ) {
        guard message.name == "tableHeight", let value = message.body as? NSNumber else { return }
        let height = CGFloat(truncating: value)
        guard height.isFinite, height > 0 else { return }
        DispatchQueue.main.async { [weak self] in self?.contentHeight = height }
    }
}

#if os(macOS)
private struct MathTableWebView: NSViewRepresentable {
    let columns: [String]
    let rows: [[String]]
    @Binding var contentHeight: CGFloat

    func makeCoordinator() -> MathTableCoordinator {
        MathTableCoordinator(contentHeight: $contentHeight)
    }

    func makeNSView(context: Context) -> WKWebView {
        let view = configuredView(context: context)
        load(view, coordinator: context.coordinator)
        return view
    }

    func updateNSView(_ view: WKWebView, context: Context) {
        load(view, coordinator: context.coordinator)
    }

    static func dismantleNSView(_ view: WKWebView, coordinator: MathTableCoordinator) {
        view.configuration.userContentController.removeScriptMessageHandler(forName: "tableHeight")
    }

    private func configuredView(context: Context) -> WKWebView {
        let controller = WKUserContentController()
        controller.add(context.coordinator, name: "tableHeight")
        let configuration = WKWebViewConfiguration()
        configuration.userContentController = controller
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.underPageBackgroundColor = .clear
        view.setValue(false, forKey: "drawsBackground")
        return view
    }

    private func load(_ view: WKWebView, coordinator: MathTableCoordinator) {
        let key = "\(columns)\u{1f}\(rows)"
        guard coordinator.loadedKey != key else { return }
        coordinator.loadedKey = key
        view.loadHTMLString(MathTableDocument.makeHTML(columns: columns, rows: rows) ?? "", baseURL: nil)
    }
}
#else
private struct MathTableWebView: UIViewRepresentable {
    let columns: [String]
    let rows: [[String]]
    @Binding var contentHeight: CGFloat

    func makeCoordinator() -> MathTableCoordinator {
        MathTableCoordinator(contentHeight: $contentHeight)
    }

    func makeUIView(context: Context) -> WKWebView {
        let controller = WKUserContentController()
        controller.add(context.coordinator, name: "tableHeight")
        let configuration = WKWebViewConfiguration()
        configuration.userContentController = controller
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.isOpaque = false
        view.backgroundColor = .clear
        load(view, coordinator: context.coordinator)
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        load(view, coordinator: context.coordinator)
    }

    static func dismantleUIView(_ view: WKWebView, coordinator: MathTableCoordinator) {
        view.configuration.userContentController.removeScriptMessageHandler(forName: "tableHeight")
    }

    private func load(_ view: WKWebView, coordinator: MathTableCoordinator) {
        let key = "\(columns)\u{1f}\(rows)"
        guard coordinator.loadedKey != key else { return }
        coordinator.loadedKey = key
        view.loadHTMLString(MathTableDocument.makeHTML(columns: columns, rows: rows) ?? "", baseURL: nil)
    }
}
#endif
