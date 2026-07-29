import Foundation

enum MathTableDocument {
    static func makeHTML(columns: [String], rows: [[String]]) -> String? {
        guard BundledKaTeXRuntime.baseURL != nil else { return nil }
        let payload = ResearchMathRuntime.json(
            ["columns": columns, "rows": rows],
            fallback: #"{"columns":[],"rows":[]}"#
        )
        return """
        <!doctype html><html><head>\(ResearchMathRuntime.head)
        <style>
        :root{color-scheme:light dark}html,body{margin:0;background:transparent;height:100%}
        body{color:CanvasText;font:-apple-system-body;overflow:auto}
        table{border-collapse:collapse;min-width:max-content;width:100%}
        th,td{padding:8px;text-align:left;vertical-align:top;border:1px solid color-mix(in srgb,CanvasText 18%,transparent)}
        th{position:sticky;top:0;background:Canvas;color:CanvasText;font-weight:600;z-index:1}
        tr:nth-child(even){background:color-mix(in srgb,CanvasText 3%,transparent)}
        .ft-math-inline{display:inline-block;margin:0 .08em}.ft-math-display{display:block;overflow-x:auto;text-align:center;margin:.5em 0}.katex-display{margin:0}
        th code,td code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;padding:.08em .28em;border-radius:4px;background:color-mix(in srgb,CanvasText 8%,transparent)}
        .ft-reference,a{color:LinkText;text-decoration:underline;cursor:pointer}.ft-reference-icon{font-weight:600}
        .ft-math-fallback{color:GrayText;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
        </style></head><body><table id="table"></table><script>
        window.ftTable=\(payload);\(ResearchMathRuntime.renderer)
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
        rows: [[String]]
    ) -> ResearchMathWebDocument {
        ResearchMathWebDocument(
            key: "table:\(columns)\u{1f}\(rows)",
            html: makeHTML(columns: columns, rows: rows) ?? "",
            baseURL: BundledKaTeXRuntime.baseURL
        )
    }
}
