import Foundation

enum MathTableDocument {
    static func makeHTML(
        columns: [String],
        rows: [[String]],
        trustedReferenceKeys: [String] = []
    ) -> String? {
        guard BundledKaTeXRuntime.baseURL != nil else { return nil }
        let payload = ResearchMathRuntime.json(
            ["columns": columns, "rows": rows],
            fallback: #"{"columns":[],"rows":[]}"#
        )
        return """
        <!doctype html><html><head>\(ResearchMathRuntime.head)
        <style>
        :root{color-scheme:light dark}html,body{margin:0;background:transparent;height:100%;overflow:hidden}
        body{color:CanvasText;font:-apple-system-body}
        #vertical{box-sizing:border-box;width:100%;height:100%;overflow-x:hidden;overflow-y:auto}
        #horizontal{box-sizing:border-box;width:100%;overflow-x:auto;overflow-y:hidden}
        table{border-collapse:collapse;min-width:max-content;width:100%}
        th,td{padding:8px;text-align:left;vertical-align:top;border:1px solid color-mix(in srgb,CanvasText 18%,transparent)}
        th{position:sticky;top:0;background:Canvas;color:CanvasText;font-weight:600;z-index:1}
        tr:nth-child(even){background:color-mix(in srgb,CanvasText 3%,transparent)}
        .ft-math-inline{display:inline-block;margin:0 .12em}.ft-math-display{display:block;overflow-x:auto;text-align:center;margin:.5em 0}.katex-display{margin:0}
        th code,td code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;line-height:1;padding:.04em .20em;border-radius:.42em;background:color-mix(in srgb,CanvasText 8%,transparent);vertical-align:baseline;-webkit-box-decoration-break:clone;box-decoration-break:clone}
        .ft-reference,a{color:LinkText;text-decoration:underline;cursor:pointer}.ft-reference-icon{display:inline-block;width:1em;height:1em;vertical-align:-.16em;background:currentColor;-webkit-mask:var(--ft-reference-symbol) center/contain no-repeat;mask:var(--ft-reference-symbol) center/contain no-repeat}
        \(ResearchDocumentReferenceCatalog.webCSS)
        .ft-math-fallback{color:GrayText;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
        </style></head><body><div id="vertical"><div id="horizontal" data-ft-measure-height><table id="table"></table></div></div><script>
        window.ftTable=\(payload);
        \(ResearchDocumentReferenceCatalog.webBootstrap(
            for: columns + rows.flatMap { $0 }
        ))
        \(ResearchDocumentReferenceCatalog.webIconBootstrap(
            for: columns + rows.flatMap { $0 }
        ))
        \(ResearchMathRuntime.trustedReferenceBootstrap(trustedReferenceKeys))
        \(ResearchMathRuntime.renderer)
        (function(){var data=window.ftTable,table=document.getElementById('table'),head=document.createElement('thead'),header=document.createElement('tr'),body=document.createElement('tbody');
        data.columns.forEach(function(value){var cell=document.createElement('th');window.ftAppendResearchRichText(cell,value);header.appendChild(cell);});
        head.appendChild(header);
        data.rows.forEach(function(row){var line=document.createElement('tr');row.forEach(function(value){var cell=document.createElement('td');window.ftAppendResearchRichText(cell,value);line.appendChild(cell);});body.appendChild(line);});
        table.appendChild(head);table.appendChild(body);window.ftReportHeight();})();
        </script></body></html>
        """
    }

    static func make(
        columns: [String],
        rows: [[String]],
        trustedReferenceKeys: [String] = []
    ) -> ResearchMathWebDocument {
        ResearchMathWebDocument(
            key: "table:\(trustedReferenceKeys)\u{1f}\(columns)\u{1f}\(rows)",
            html: makeHTML(
                columns: columns,
                rows: rows,
                trustedReferenceKeys: trustedReferenceKeys
            ) ?? "",
            baseURL: BundledKaTeXRuntime.baseURL
        )
    }
}
