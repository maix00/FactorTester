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

    static let renderer = ResearchDocumentReferenceCatalog.webBootstrap + #"""
    window.ftTrustedReferences=window.ftTrustedReferences||new Set();
    window.ftRenderMath=function(root,latex,displayMode){
      try{katex.render(latex,root,{displayMode:displayMode,throwOnError:true,strict:'warn',trust:false,maxSize:24,maxExpand:1000});}
      catch(error){root.classList.add('ft-math-fallback');root.textContent=(displayMode?'\\[':'\\(')+latex+(displayMode?'\\]':'\\)');}
    };
    window.ftAppendResearchRichText=function(root,source){
      var input=String(source),cursor=0,token=/`([^`\r\n]+)`|\[((?:\\[\[\]\\]|[^\[\]\\\r\n]){1,512})\]\(([^()\s]+)\)|\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]|\$\$([\s\S]+?)\$\$/g,match;
      function text(value){
        if(!value){return;}
        var previous=root.lastElementChild;
        if(previous&&previous.classList.contains('ft-reference')&&/^\s*=/.test(value)){
          value=' = '+value.replace(/^\s*=\s*/,'');
        }
        root.appendChild(document.createTextNode(value));
      }
      while((match=token.exec(input))!==null){
        text(input.slice(cursor,match.index));
        if(match[1]!==undefined){var code=document.createElement('code');code.textContent=match[1];root.appendChild(code);}
        else if(match[2]!==undefined){
          var label=match[2].replace(/\\([\[\]\\])/g,'$1'),target=match[3];
          if(target.indexOf('factortester://')===0){
            var parts=target.slice(15).split('/');
            var key='';try{key=parts[0]+'\u001f'+decodeURIComponent(parts[1]);}catch(error){}
            if(parts.length===2&&window.ftReferencePresentation[parts[0]]&&window.ftTrustedReferences.has(key)){var reference=document.createElement('a'),icon=document.createElement('span');reference.className='ft-reference';reference.href=target;reference.dataset.referenceTone=window.ftReferenceTone(parts[0]);reference.dataset.referenceLabel=label;icon.className='ft-reference-icon';icon.textContent=window.ftReferenceIcon(parts[0]);reference.appendChild(icon);reference.appendChild(document.createTextNode(' '+label));reference.addEventListener('click',function(event){event.preventDefault();window.webkit.messageHandlers.researchReference.postMessage({href:this.href,label:this.dataset.referenceLabel});});root.appendChild(reference);}
            else{text(label);}
          }else if(/^https?:\/\//.test(target)){var link=document.createElement('a');link.href=target;link.textContent=label;root.appendChild(link);}
          else{text(match[0]);}
        }else{var math=document.createElement(match[4]!==undefined?'span':'div');math.className=match[4]!==undefined?'ft-math-inline':'ft-math-display';window.ftRenderMath(math,match[4]||match[5]||match[6],match[4]===undefined);root.appendChild(math);}
        cursor=token.lastIndex;
      }
      text(input.slice(cursor));
    };
    window.ftReferenceDescriptor=function(kind){return window.ftReferencePresentation[kind]||{icon:'↗',tone:'link'};};
    window.ftReferenceIcon=function(kind){return window.ftReferenceDescriptor(kind).icon;};
    window.ftReferenceTone=function(kind){return window.ftReferenceDescriptor(kind).tone;};
    window.ftReportHeight=function(){requestAnimationFrame(function(){requestAnimationFrame(function(){window.webkit.messageHandlers.researchContentHeight.postMessage(Math.ceil(document.documentElement.scrollHeight));});});};
    """#

    static func json(_ value: Any, fallback: String) -> String {
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value),
              let result = String(data: data, encoding: .utf8)
        else { return fallback }
        return result
    }

    static func trustedReferenceBootstrap(_ keys: [String]) -> String {
        let payload = json(keys, fallback: "[]")
        return "window.ftTrustedReferences=new Set(\(payload));"
    }
}
