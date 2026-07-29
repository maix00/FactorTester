import Foundation

enum BundledKaTeXRuntime {
    static let directoryName = "KaTeX"
    static let scriptFilename = "katex.min.js"
    static let stylesheetFilename = "katex.min.css"

    static let baseURL: URL? = Bundle.main.url(
        forResource: "katex.min",
        withExtension: "js",
        subdirectory: directoryName
    )?.deletingLastPathComponent()
}

enum ResearchMathRuntime {
    static let heightHandlerName = "researchContentHeight"

    static let head = """
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="\(BundledKaTeXRuntime.stylesheetFilename)">
    <script src="\(BundledKaTeXRuntime.scriptFilename)"></script>
    """

    static let renderer = #"""
    window.ftRenderMath=function(root,latex,displayMode){
      try{katex.render(latex,root,{displayMode:displayMode,throwOnError:true,strict:'warn',trust:false,maxSize:24,maxExpand:1000});}
      catch(error){root.classList.add('ft-math-fallback');root.textContent=(displayMode?'\\[':'\\(')+latex+(displayMode?'\\]':'\\)');}
    };
    window.ftAppendResearchRichText=function(root,source){
      var input=String(source),cursor=0,token=/`([^`\r\n]+)`|\[([^\]\r\n]{1,256})\]\(([^()\s]+)\)|\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]|\$\$([\s\S]+?)\$\$/g,match;
      function text(value){if(value){root.appendChild(document.createTextNode(value));}}
      while((match=token.exec(input))!==null){
        text(input.slice(cursor,match.index));
        if(match[1]!==undefined){var code=document.createElement('code');code.textContent=match[1];root.appendChild(code);}
        else if(match[2]!==undefined){
          var label=match[2],target=match[3];
          if(target.indexOf('factortester://')===0){
            var parts=target.slice(16).split('/');
            if(parts.length===2){var reference=document.createElement('a'),icon=document.createElement('span');reference.className='ft-reference';reference.href=target;icon.className='ft-reference-icon';icon.textContent=window.ftReferenceIcon(parts[0]);reference.appendChild(icon);reference.appendChild(document.createTextNode(' '+label));reference.addEventListener('click',function(event){event.preventDefault();window.webkit.messageHandlers.researchReference.postMessage({href:this.href,label:this.textContent.slice(2)});});root.appendChild(reference);}
            else{text(match[0]);}
          }else if(/^https?:\/\//.test(target)){var link=document.createElement('a');link.href=target;link.textContent=label;root.appendChild(link);}
          else{text(match[0]);}
        }else{var math=document.createElement(match[4]!==undefined?'span':'div');math.className=match[4]!==undefined?'ft-math-inline':'ft-math-display';window.ftRenderMath(math,match[4]||match[5]||match[6],match[4]===undefined);root.appendChild(math);}
        cursor=token.lastIndex;
      }
      text(input.slice(cursor));
    };
    window.ftReferenceIcon=function(kind){return({evidence:'⌕',obligation:'✓',task:'☑',job:'☑',claim:'❝',artifact:'⌇',report_requirement:'☷',trial_plan:'☷',graph_reference:'⌘',checkpoint:'⚑',run:'▷',run_spec:'≡',delta:'↔'})[kind]||'↗';};
    window.ftReportHeight=function(){requestAnimationFrame(function(){requestAnimationFrame(function(){window.webkit.messageHandlers.researchContentHeight.postMessage(Math.ceil(document.documentElement.scrollHeight));});});};
    """#

    static func json(_ value: Any, fallback: String) -> String {
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value),
              let result = String(data: data, encoding: .utf8)
        else { return fallback }
        return result
    }
}
