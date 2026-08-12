#if os(macOS)
import Foundation

enum ResearchInlineMathDocument {
    static let horizontalPadding: CGFloat = 2

    static func html(latex: String, fontSize: CGFloat) -> String {
        let payload = ResearchMathRuntime.json([latex], fallback: #"[""]"#)
        return """
        <!doctype html><html><head>\(ResearchMathRuntime.head)<style>
        html,body{margin:0;padding:0;background:transparent;overflow:hidden}
        #stage{position:absolute;left:16px;top:64px;white-space:nowrap;
          font-size:\(fontSize)px;line-height:1}
        #formula{display:inline-block;color:#000;white-space:nowrap}
        #baseline{display:inline-block;width:0;height:0;margin:0;padding:0;
          vertical-align:baseline}
        </style></head><body><span id="stage"><span id="formula"></span><span
          id="baseline"></span></span><script>
        katex.render(\(payload)[0],document.getElementById('formula'),{
          displayMode:false,throwOnError:false,strict:'warn',trust:false
        });
        </script></body></html>
        """
    }

    static let metricsScript = """
    await document.fonts.ready;
    const root = document.querySelector('#formula .katex-html');
    const rootRect = root.getBoundingClientRect();
    const struts = Array.from(root.querySelectorAll('.strut'))
      .map(node => node.getBoundingClientRect());
    const top = struts.length
      ? Math.min(...struts.map(rect => rect.top))
      : rootRect.top;
    const bottom = struts.length
      ? Math.max(...struts.map(rect => rect.bottom))
      : rootRect.bottom;
    const padding = \(horizontalPadding);
    const x = Math.floor(rootRect.left - padding);
    const y = Math.floor(top);
    const right = Math.ceil(rootRect.right + padding);
    const lower = Math.ceil(bottom);
    return {
      x: x, y: y, width: right - x, height: lower - y,
      baseline: document.getElementById('baseline')
        .getBoundingClientRect().top - y
    };
    """
}
#endif
