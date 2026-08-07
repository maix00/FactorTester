import SwiftUI
import WebKit

/// One native WebView is retained per client tab while its SwiftUI wrapper
/// can be unmounted when another tab is selected.
final class WebPageSession {
    var webView: WKWebView?
    var loadedURL: URL?
    var loadedToken = ""
    var loadedServicePort = ""

    func reset() {
        webView?.stopLoading()
        webView?.navigationDelegate = nil
        webView = nil
        loadedURL = nil
        loadedToken = ""
        loadedServicePort = ""
    }
}

/// 「转发到 web 版本换页」的承载控件。
///
/// 尚未做原生实现的模块，直接在 App 内用 WKWebView 加载服务器对应路由，
/// 复用现有 web 前端 —— 这正是 issue#122「单一实现、多端复用」的过渡形态：
/// 原生页写一个少一个，其余自动回落到 web，体验仍包在统一的原生外壳里。
///
/// 登录态桥接：把 URLSession（原生登录用）拿到的 cookie 注入 WebView 的
/// cookie store，避免进 web 页后又要登录一次。
struct WebPageView: View {
    let path: String
    /// A report reference may lead to a real external URL.  It is kept
    /// separate from `path` so external pages never receive Manager auth
    /// state or the embedded presentation query.
    var externalURL: URL? = nil
    var webSession: WebPageSession? = nil
    var onReference: ((ResearchDocumentTypedLink) -> Void)? = nil
    var onNavigation: ((String) -> Void)? = nil
    var onExternalURL: ((URL) -> Void)? = nil
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var languageStore: LanguageStore
    @State private var loadError: String?
    @State private var reloadID = UUID()
    @State private var showLogin = false

    var body: some View {
        Group {
            if let loadError {
                VStack(spacing: 12) {
                    Image(systemName: "network.slash")
                        .font(.largeTitle)
                    Text("页面无法打开").font(.headline)
                    Text(loadError)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                    HStack {
                        Button("重新加载") {
                            self.loadError = nil
                            if let webSession {
                                webSession.reset()
                            }
                            reloadID = UUID()
                        }
                        Button("登录 / 注册") { showLogin = true }
                            .buttonStyle(.borderedProminent)
                    }
                }
                .padding(30)
            } else if let url = resolvedURL {
                WebViewRepresentable(
                    url: url,
                    syncServerCookies: externalURL == nil,
                    enforceEmbeddedPresentation: externalURL == nil,
                    serverOrigin: externalURL == nil
                        ? ManagerConfig.shared.baseURL : nil,
                    sessionToken: externalURL == nil
                        ? ManagerSessionTokenStore.read() : "",
                    servicePort: externalURL == nil
                        ? ServerConfig.shared.port : "",
                    webSession: webSession,
                    allowsLocalFactorCatalog: externalURL == nil
                        && (path == "/factors" || path.hasPrefix("/factors/")),
                    onReference: onReference,
                    onNavigation: onNavigation,
                    onExternalURL: onExternalURL,
                    loadError: $loadError
                )
                .id(reloadID)
                .ignoresSafeArea(edges: .bottom)
            } else {
                Text("服务器地址无效，请在设置中修正。")
                    .foregroundStyle(.secondary)
            }
        }
        .sheet(isPresented: $showLogin) {
            LoginView { success in
                showLogin = false
                if success { loadError = nil; reloadID = UUID() }
            }
            .environmentObject(session)
        }
    }

    private var resolvedURL: URL? {
        if let externalURL { return externalURL }
        guard let rawURL = ManagerConfig.shared.url(forPath: path) else {
            return nil
        }
        return EmbeddedPresentationURL.add(
            to: rawURL,
            language: languageStore.selection
        )
    }
}

enum EmbeddedPresentationURL {
    static func add(
        to url: URL,
        language: AppLanguage? = nil
    ) -> URL? {
        guard var components = URLComponents(
            url: url,
            resolvingAgainstBaseURL: false
        ) else { return nil }
        var items = components.queryItems ?? []
        items.removeAll { $0.name == "presentation" }
        items.append(URLQueryItem(name: "presentation", value: "embedded"))
        if let language {
            items.removeAll { $0.name == "lang" }
            items.append(URLQueryItem(name: "lang", value: language.rawValue))
        }
        components.queryItems = items
        return components.url
    }

    static func rewrite(_ url: URL, serverOrigin: URL) -> URL? {
        guard isSameOrigin(url, serverOrigin) else { return nil }
        return add(to: url)
    }

    private static func isSameOrigin(_ lhs: URL, _ rhs: URL) -> Bool {
        lhs.scheme?.lowercased() == rhs.scheme?.lowercased()
            && lhs.host?.lowercased() == rhs.host?.lowercased()
            && effectivePort(lhs) == effectivePort(rhs)
    }

    private static func effectivePort(_ url: URL) -> Int? {
        if let port = url.port { return port }
        switch url.scheme?.lowercased() {
        case "http": return 80
        case "https": return 443
        default: return nil
        }
    }
}

#if os(iOS)
import UIKit
typealias PlatformViewRepresentable = UIViewRepresentable
#else
import AppKit
typealias PlatformViewRepresentable = NSViewRepresentable
#endif

struct WebViewRepresentable: PlatformViewRepresentable {
    let url: URL
    let syncServerCookies: Bool
    let enforceEmbeddedPresentation: Bool
    let serverOrigin: URL?
    let sessionToken: String
    let servicePort: String
    let webSession: WebPageSession?
    let allowsLocalFactorCatalog: Bool
    let onReference: ((ResearchDocumentTypedLink) -> Void)?
    let onNavigation: ((String) -> Void)?
    let onExternalURL: ((URL) -> Void)?
    @Binding var loadError: String?

    init(
        url: URL,
        syncServerCookies: Bool,
        enforceEmbeddedPresentation: Bool = false,
        serverOrigin: URL? = nil,
        sessionToken: String = "",
        servicePort: String = "",
        webSession: WebPageSession? = nil,
        allowsLocalFactorCatalog: Bool = false,
        onReference: ((ResearchDocumentTypedLink) -> Void)? = nil,
        onNavigation: ((String) -> Void)? = nil,
        onExternalURL: ((URL) -> Void)? = nil,
        loadError: Binding<String?> = .constant(nil)
    ) {
        self.url = url
        self.syncServerCookies = syncServerCookies
        self.enforceEmbeddedPresentation = enforceEmbeddedPresentation
        self.serverOrigin = serverOrigin
        self.sessionToken = sessionToken
        self.servicePort = servicePort
        self.webSession = webSession
        self.allowsLocalFactorCatalog = allowsLocalFactorCatalog
        self.onReference = onReference
        self.onNavigation = onNavigation
        self.onExternalURL = onExternalURL
        _loadError = loadError
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(
            loadError: $loadError,
            enforceEmbeddedPresentation: enforceEmbeddedPresentation,
            serverOrigin: serverOrigin,
            onReference: onReference,
            onNavigation: onNavigation,
            onExternalURL: onExternalURL
        )
    }

    private func makeWebView(context: Context) -> WKWebView {
        if let existing = webSession?.webView {
            existing.removeFromSuperview()
            existing.navigationDelegate = context.coordinator
            existing.configuration.userContentController.removeScriptMessageHandler(
                forName: ResearchDocumentWebReferenceMessage.handlerName
            )
            existing.configuration.userContentController.removeScriptMessageHandler(
                forName: ResearchDocumentWebNavigationMessage.handlerName
            )
            existing.configuration.userContentController.add(
                context.coordinator,
                name: ResearchDocumentWebReferenceMessage.handlerName
            )
            existing.configuration.userContentController.add(
                context.coordinator,
                name: ResearchDocumentWebNavigationMessage.handlerName
            )
            Task { await prepareAndLoad(existing) }
            return existing
        }
        let configuration = WKWebViewConfiguration()
        #if os(macOS)
        if allowsLocalFactorCatalog {
            configuration.userContentController.addScriptMessageHandler(
                FactorLibraryLocalBridge(),
                contentWorld: .page,
                name: FactorLibraryLocalBridgeContract.messageName
            )
        }
        #endif
        configuration.userContentController.add(
            context.coordinator,
            name: ResearchDocumentWebReferenceMessage.handlerName
        )
        configuration.userContentController.add(
            context.coordinator,
            name: ResearchDocumentWebNavigationMessage.handlerName
        )
        if !sessionToken.isEmpty,
           let data = try? JSONEncoder().encode(sessionToken),
           let literal = String(data: data, encoding: .utf8) {
            configuration.userContentController.addUserScript(WKUserScript(
                source: "localStorage.setItem('ft-session', \(literal));",
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            ))
        }
        let selectedPort = servicePort.trimmingCharacters(in: .whitespaces)
        if let data = try? JSONEncoder().encode(selectedPort),
           let literal = String(data: data, encoding: .utf8) {
            let source = selectedPort.isEmpty
                ? "localStorage.removeItem('ft-service-port');"
                : "localStorage.setItem('ft-service-port', \(literal));"
            configuration.userContentController.addUserScript(WKUserScript(
                source: source,
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            ))
        }
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webSession?.webView = webView
        Task { await prepareAndLoad(webView) }
        return webView
    }

    #if os(iOS)
    func makeUIView(context: Context) -> WKWebView { makeWebView(context: context) }
    func updateUIView(_ webView: WKWebView, context: Context) {
        webView.navigationDelegate = context.coordinator
        Task { await prepareAndLoad(webView) }
    }
    #else
    func makeNSView(context: Context) -> WKWebView { makeWebView(context: context) }
    func updateNSView(_ webView: WKWebView, context: Context) {
        webView.navigationDelegate = context.coordinator
        Task { await prepareAndLoad(webView) }
    }
    #endif

    #if os(iOS)
    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        dismantle(webView)
    }
    #else
    static func dismantleNSView(_ webView: WKWebView, coordinator: Coordinator) {
        dismantle(webView)
    }
    #endif

    private static func dismantle(_ webView: WKWebView) {
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: ResearchDocumentWebReferenceMessage.handlerName
        )
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: ResearchDocumentWebNavigationMessage.handlerName
        )
        webView.navigationDelegate = nil
    }

    /// 先把共享 HTTPCookieStorage 里的 cookie 灌进 WebView，再加载目标页。
    @MainActor
    private func prepareAndLoad(_ webView: WKWebView) async {
        let needsNavigation = webSession?.loadedURL != url
            || webSession?.loadedToken != sessionToken
            || webSession?.loadedServicePort != servicePort
        guard needsNavigation else { return }
        webSession?.loadedURL = url
        webSession?.loadedToken = sessionToken
        webSession?.loadedServicePort = servicePort
        let controller = webView.configuration.userContentController
        controller.removeAllUserScripts()
        if !sessionToken.isEmpty,
           let data = try? JSONEncoder().encode(sessionToken),
           let literal = String(data: data, encoding: .utf8) {
            controller.addUserScript(WKUserScript(
                source: "localStorage.setItem('ft-session', \(literal));",
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            ))
        }
        let selectedPort = servicePort.trimmingCharacters(in: .whitespaces)
        if let data = try? JSONEncoder().encode(selectedPort),
           let literal = String(data: data, encoding: .utf8) {
            let source = selectedPort.isEmpty
                ? "localStorage.removeItem('ft-service-port');"
                : "localStorage.setItem('ft-service-port', \(literal));"
            controller.addUserScript(WKUserScript(
                source: source,
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true
            ))
        }
        if syncServerCookies, let host = serverOrigin?.host ?? url.host {
            let store = webView.configuration.websiteDataStore.httpCookieStore
            let cookies = (HTTPCookieStorage.shared.cookies ?? [])
                .filter { $0.domain.contains(host) }
            for cookie in cookies { await store.setCookie(cookie) }
        }

        webView.load(URLRequest(url: url))
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        @Binding private var loadError: String?
        private let enforceEmbeddedPresentation: Bool
        private let serverOrigin: URL?
        private let onReference: ((ResearchDocumentTypedLink) -> Void)?
        private let onNavigation: ((String) -> Void)?
        private let onExternalURL: ((URL) -> Void)?

        init(
            loadError: Binding<String?>,
            enforceEmbeddedPresentation: Bool,
            serverOrigin: URL?,
            onReference: ((ResearchDocumentTypedLink) -> Void)?,
            onNavigation: ((String) -> Void)?,
            onExternalURL: ((URL) -> Void)?
        ) {
            _loadError = loadError
            self.enforceEmbeddedPresentation = enforceEmbeddedPresentation
            self.serverOrigin = serverOrigin
            self.onReference = onReference
            self.onNavigation = onNavigation
            self.onExternalURL = onExternalURL
        }

        func userContentController(
            _ userContentController: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            if message.name == ResearchDocumentWebNavigationMessage.handlerName,
               let path = ResearchDocumentWebNavigationMessage.path(from: message.body) {
                DispatchQueue.main.async { [weak self] in
                    self?.onNavigation?(path)
                }
                return
            }
            guard message.name == ResearchDocumentWebReferenceMessage.handlerName,
                  let reference = ResearchDocumentWebReferenceMessage.decode(message.body)
            else { return }
            DispatchQueue.main.async { [weak self] in
                self?.onReference?(reference)
            }
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard enforceEmbeddedPresentation,
                  navigationAction.targetFrame?.isMainFrame != false,
                  let destination = navigationAction.request.url,
                  let origin = serverOrigin,
                  let rewritten = EmbeddedPresentationURL.rewrite(
                      destination,
                      serverOrigin: origin
                  ),
                  rewritten != destination else {
                decisionHandler(.allow)
                return
            }
            webView.load(URLRequest(url: rewritten))
            decisionHandler(.cancel)
        }

        /// `target="_blank"` links do not have a browser window inside the
        /// client.  Hand the URL to the Swift tab stack instead of silently
        /// dropping the navigation.
        func webView(
            _ webView: WKWebView,
            createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction,
            windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            guard let url = navigationAction.request.url else { return nil }
            DispatchQueue.main.async { [weak self] in
                self?.onExternalURL?(url)
            }
            return nil
        }

        func webView(
            _ webView: WKWebView,
            didFail navigation: WKNavigation!,
            withError error: Error
        ) {
            loadError = error.localizedDescription
        }

        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            loadError = error.localizedDescription
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationResponse: WKNavigationResponse,
            decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
        ) {
            let status = (
                navigationResponse.response as? HTTPURLResponse
            )?.statusCode
            if status == 401 || status == 403 {
                loadError = L10n.text("登录已失效或没有访问权限。")
                decisionHandler(.cancel)
            } else {
                decisionHandler(.allow)
            }
        }

        // 放行自签名证书（与 SelfSignedTrustDelegate 同一策略）。
        func webView(_ webView: WKWebView,
                     didReceive challenge: URLAuthenticationChallenge,
                     completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
            let configuredHost = serverOrigin?.host?.lowercased() ?? ""
            if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
               challenge.protectionSpace.host.lowercased() == configuredHost,
               let trust = challenge.protectionSpace.serverTrust {
                completionHandler(.useCredential, URLCredential(trust: trust))
            } else {
                completionHandler(.performDefaultHandling, nil)
            }
        }
    }
}
