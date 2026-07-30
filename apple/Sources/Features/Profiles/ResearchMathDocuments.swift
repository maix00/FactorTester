import Foundation

struct ResearchMathWebDocument {
    let key: String
    let html: String
    let baseURL: URL?
}

enum MathFormulaDocument {
    static func bootstrapScript(latex: String, fallback: String) -> String {
        let payload = ResearchMathRuntime.json(
            [latex, fallback],
            fallback: #"["","因子公式"]"#
        )
        return "window.ftFormulaPayload=\(payload);"
    }

    static func makeHTML(latex: String, fallback: String) -> String? {
        guard BundledKaTeXRuntime.baseURL != nil else { return nil }
        return """
        <!doctype html><html><head>\(ResearchMathRuntime.head)
        <style>
        :root{color-scheme:light dark}html,body{margin:0;padding:0;background:transparent}
        body{color:CanvasText;font:-apple-system-body;overflow:hidden}
        #formula{box-sizing:border-box;width:100%;padding:12px 14px;overflow-x:auto;text-align:center}
        #fallback{display:none;box-sizing:border-box;width:100%;padding:12px 14px;color:GrayText}
        .katex-display{margin:0}.ft-math-fallback{color:GrayText;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
        </style></head><body><div id="formula"></div><div id="fallback"></div>
        <script>\(bootstrapScript(latex: latex, fallback: fallback))
        \(ResearchMathRuntime.renderer)
        try{window.ftRenderMath(document.getElementById('formula'),window.ftFormulaPayload[0],true);}
        catch(error){document.getElementById('formula').style.display='none';var fallback=document.getElementById('fallback');fallback.style.display='block';fallback.textContent=window.ftFormulaPayload[1];}
        window.ftReportHeight();</script></body></html>
        """
    }

    static func make(latex: String, fallback: String) -> ResearchMathWebDocument {
        ResearchMathWebDocument(
            key: "formula:\(latex)",
            html: makeHTML(latex: latex, fallback: fallback) ?? fallback,
            baseURL: BundledKaTeXRuntime.baseURL
        )
    }
}

enum MathRichTextDocument {
    static func makeHTML(
        _ text: String,
        trustedReferenceKeys: [String] = []
    ) -> String? {
        guard BundledKaTeXRuntime.baseURL != nil else { return nil }
        let payload = ResearchMathRuntime.json([text], fallback: #"[""]"#)
        return """
        <!doctype html><html><head>\(ResearchMathRuntime.head)
        <style>
        :root{color-scheme:light dark}html,body{margin:0;padding:0;background:transparent}
        body{color:CanvasText;font:-apple-system-body;line-height:1.55;overflow:hidden}
        #content{box-sizing:border-box;width:100%;padding:0}
        code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;padding:.08em .28em;border-radius:4px;background:color-mix(in srgb,CanvasText 8%,transparent)}
        .ft-math-inline{display:inline-block;margin:0 .12em}.ft-math-display{display:block;overflow-x:auto;text-align:center;margin:.65em 0}.katex-display{margin:0}
        .ft-reference,a{color:LinkText;text-decoration:underline;cursor:pointer}.ft-reference-icon{display:inline-block;width:1em;height:1em;vertical-align:-.16em;background:currentColor;-webkit-mask:var(--ft-reference-symbol) center/contain no-repeat;mask:var(--ft-reference-symbol) center/contain no-repeat}
        \(ResearchDocumentReferenceCatalog.webCSS)
        .ft-math-fallback{color:GrayText;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
        </style></head><body><div id="content"></div><script>
        window.ftRichText=\(payload)[0];
        \(ResearchMathRuntime.trustedReferenceBootstrap(trustedReferenceKeys))
        \(ResearchMathRuntime.renderer)
        window.ftAppendResearchRichText(document.getElementById('content'),window.ftRichText);
        window.ftReportHeight();</script></body></html>
        """
    }

    static func make(
        _ text: String,
        trustedReferenceKeys: [String] = []
    ) -> ResearchMathWebDocument {
        ResearchMathWebDocument(
            key: "rich:\(trustedReferenceKeys)\u{1f}\(text)",
            html: makeHTML(
                text,
                trustedReferenceKeys: trustedReferenceKeys
            ) ?? text,
            baseURL: BundledKaTeXRuntime.baseURL
        )
    }
}
