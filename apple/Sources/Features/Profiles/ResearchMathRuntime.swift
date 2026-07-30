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
    window.ftAppendReference=function(root,kind,target,label,href){
      var reference=document.createElement('a'),icon=document.createElement('span');
      reference.className='ft-reference';
      reference.href=href||('factortester://'+kind+'/'+encodeURIComponent(target));
      reference.dataset.referenceTone=window.ftReferenceTone(kind);
      reference.dataset.referenceLabel=label;
      icon.className='ft-reference-icon';
      icon.style.setProperty(
        '--ft-reference-symbol',
        'url("factortester-symbol://'+encodeURIComponent(kind)+'")'
      );
      icon.setAttribute('aria-hidden','true');
      reference.appendChild(icon);
      reference.appendChild(document.createTextNode(' '+label));
      reference.addEventListener('click',function(event){
        event.preventDefault();
        window.webkit.messageHandlers.researchReference.postMessage({
          href:this.href,label:this.dataset.referenceLabel
        });
      });
      root.appendChild(reference);
    };
    window.ftSafeLocalReference=function(target){
      if(!target||target.length>1024||target[0]=='/'||target[0]=='~'||target.indexOf('\\')>=0){return false;}
      var parts=target.split('/');
      return parts.length>1&&parts.every(function(value){return value&&value!=='.'&&value!=='..';})
        &&/\.(?:md|markdown|json|csv|py|txt|pdf|png|jpe?g|svg)$/i.test(target);
    };
    window.ftRenderMath=function(root,latex,displayMode){
      try{katex.render(latex,root,{displayMode:displayMode,throwOnError:true,strict:'warn',trust:false,maxSize:24,maxExpand:1000});}
      catch(error){root.classList.add('ft-math-fallback');root.textContent=(displayMode?'\\[':'\\(')+latex+(displayMode?'\\]':'\\)');}
    };
    window.ftAppendResearchRichText=function(root,source){
      var input=String(source),cursor=0,token=/`([^`\r\n]+)`|\[((?:\\[\[\]\\]|[^\[\]\\\r\n]){1,512})\]\(([^()\s]+)\)|\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]|\$\$([\s\S]+?)\$\$|(?<![`\\\w])(https?:\/\/[^\s<>()\]]+)|(?<![`\\\w\/])((?:[^\s\[\]()<>\/]+\/)+[^\s\[\]()<>\/]+\.(?:md|markdown|json|csv|py|txt|pdf|png|jpe?g|svg))(?![\w\/])/gi,match;
      function text(value){
        if(!value){return;}
        value=value.replace(/(^|[^<>=!])\s*=\s*(?=$|[^=>])/g,function(_,prefix){return prefix+' = ';});
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
            if(parts.length===2&&window.ftReferencePresentation[parts[0]]&&window.ftTrustedReferences.has(key)){window.ftAppendReference(root,parts[0],decodeURIComponent(parts[1]),label,target);}
            else{text(label);}
          }else if(/^https?:\/\//i.test(target)){window.ftAppendReference(root,'url',target,label);}
          else if(window.ftSafeLocalReference(target)){window.ftAppendReference(root,'file',target,label);}
          else{text(match[0]);}
        }else if(match[7]!==undefined){window.ftAppendReference(root,'url',match[7],match[7]);}
        else if(match[8]!==undefined){window.ftAppendReference(root,'file',match[8],match[8]);}
        else{var math=document.createElement(match[4]!==undefined?'span':'div');math.className=match[4]!==undefined?'ft-math-inline':'ft-math-display';window.ftRenderMath(math,match[4]||match[5]||match[6],match[4]===undefined);root.appendChild(math);}
        cursor=token.lastIndex;
      }
      text(input.slice(cursor));
    };
    window.ftReferenceDescriptor=function(kind){return window.ftReferencePresentation[kind]||{icon:'↗',tone:'link'};};
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
