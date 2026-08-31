import SwiftUI
import WebKit

/// A tab may retain a WebView while it is in the small session cache.  The
/// cache is bounded by `ClientTabSessionStore`; evicted tabs keep their route
/// and lightweight Swift state but release the WebContent process.
final class WebPageSession {
    var webView: WKWebView?
    var loadedURL: URL?
    var loadedToken = ""
    var loadedServicePort = ""
    var loadedVisitorID = ""

    func reset() {
        releaseWebView()
        loadedURL = nil
        loadedToken = ""
        loadedServicePort = ""
        loadedVisitorID = ""
    }

    /// Release the expensive native view without retaining a detached
    /// WebContent process.  The session can be recreated from its owning tab
    /// when the tab becomes active again.
    func releaseWebView() {
        webView?.removeFromSuperview()
        webView?.stopLoading()
        webView?.navigationDelegate = nil
        webView?.uiDelegate = nil
        webView?.configuration.userContentController.removeAllUserScripts()
        webView?.configuration.userContentController.removeScriptMessageHandler(
            forName: ResearchDocumentWebReferenceMessage.handlerName
        )
        webView?.configuration.userContentController.removeScriptMessageHandler(
            forName: ResearchDocumentWebNavigationMessage.handlerName
        )
        webView?.configuration.userContentController.removeScriptMessageHandler(
            forName: ClientWebAuthenticationMessage.handlerName
        )
        #if os(macOS)
        webView?.configuration.userContentController.removeScriptMessageHandler(
            forName: ClientLocalCatalogBridgeContract.messageName
        )
        webView?.configuration.userContentController.removeScriptMessageHandler(
            forName: LocalRunBridgeContract.messageName
        )
        #endif
        webView = nil
    }
}

/// The presentation owner for a Manager-backed Web page.
///
/// Embedded pages are hosted by a native Swift tab and therefore hide the Web
/// shell.  Standalone pages own the complete Web shell, including its sidebar
/// and opened-tab list.  Keeping this distinction explicit prevents a client
/// from accidentally rendering two navigation systems at once.
enum WebPresentationMode: Equatable {
    case embedded
    case standalone

    var usesEmbeddedShell: Bool {
        self == .embedded
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
    var presentation: WebPresentationMode = .embedded
    /// A report reference may lead to a real external URL.  It is kept
    /// separate from `path` so external pages never receive Manager auth
    /// state or a Manager presentation query.
    var externalURL: URL? = nil
    var webSession: WebPageSession? = nil
    var onReference: ((ResearchDocumentTypedLink) -> Void)? = nil
    var onNavigation: ((String) -> Void)? = nil
    var onExternalURL: ((URL) -> Void)? = nil
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var languageStore: LanguageStore
    @State private var loadError: String?
    @State private var reloadID = UUID()
    // Some generic module callers do not own a ClientTabSession. Keep one
    // lightweight WebPageSession at the view boundary so SwiftUI updates do
    // not treat every body refresh as a fresh navigation.
    @State private var ownedWebSession = WebPageSession()

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
                            activeWebSession.reset()
                            reloadID = UUID()
                        }
                    }
                }
                .padding(30)
            } else if let url = resolvedURL {
                WebViewRepresentable(
                    url: url,
                    syncServerCookies: externalURL == nil,
                    enforceEmbeddedPresentation: externalURL == nil
                        && presentation.usesEmbeddedShell,
                    serverOrigin: externalURL == nil
                        ? ManagerConfig.shared.baseURL : nil,
                    sessionToken: externalURL == nil
                        ? ManagerSessionTokenStore.read() : "",
                    servicePort: externalURL == nil
                        ? ServerConfig.shared.port : "",
                    clientAccess: externalURL == nil,
                    visitorID: externalURL == nil
                        ? VisitorIdentityStore.current() : "",
                    webSession: activeWebSession,
                    allowsLocalCatalog: externalURL == nil
                        && (presentation == .standalone
                            || ClientLocalCatalogBridgeContract.allowsEmbeddedPage(
                                path: path
                            )),
                    onReference: onReference,
                    onNavigation: onNavigation,
                    onExternalURL: onExternalURL,
                    onAuthentication: handleAuthentication,
                    loadError: $loadError
                )
                .id(reloadID)
                .ignoresSafeArea(edges: .bottom)
            } else {
                Text("服务器地址无效，请在设置中修正。")
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var resolvedURL: URL? {
        if let externalURL { return externalURL }
        guard let rawURL = ManagerConfig.shared.url(forPath: path) else {
            return nil
        }
        if presentation == .standalone {
            return EmbeddedPresentationURL.standalone(
                to: rawURL,
                language: languageStore.selection
            )
        }
        // The database module is itself a Manager-owned tab.  Load the
        // Manager shell first; it then creates the authenticated sqlite-web
        // iframe.  Loading `presentation=embedded` here bypasses that shell
        // and turns a missing Manager cookie into a raw JSON login error.
        if path == "/sqlite-web" || path == "/sqlite-web/" {
            return EmbeddedPresentationURL.standalone(
                to: rawURL,
                language: languageStore.selection
            )
        }
        return EmbeddedPresentationURL.add(
            to: rawURL,
            language: languageStore.selection,
            client: isTestWorkbenchPage ? "swift" : nil
        )
    }

    private var isTestWorkbenchPage: Bool {
        path == "/ic-test" || path == "/backtest"
    }

    private var activeWebSession: WebPageSession {
        webSession ?? ownedWebSession
    }

    @MainActor
    private func handleAuthentication(
        _ action: ClientWebAuthenticationMessage.Action
    ) {
        switch action {
        case .logout:
            Task { @MainActor in
                await session.logout()
                activeWebSession.reset()
                loadError = nil
                reloadID = UUID()
            }
        case .sessionUpdated:
            Task { @MainActor in
                if let webView = activeWebSession.webView {
                    await WebSessionCookieSynchronizer.importManagerSession(
                        from: webView,
                        endpoint: ManagerConfig.shared.baseURL
                    )
                }
                _ = await session.refresh()
            }
        }
    }
}

enum EmbeddedPresentationURL {
    static func add(
        to url: URL,
        language: AppLanguage? = nil,
        client: String? = nil
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
        if let client {
            items.removeAll { $0.name == "client" }
            items.append(URLQueryItem(name: "client", value: client))
        }
        components.queryItems = items
        return components.url
    }

    static func standalone(
        to url: URL,
        language: AppLanguage? = nil
    ) -> URL? {
        guard var components = URLComponents(
            url: url,
            resolvingAgainstBaseURL: false
        ) else { return nil }
        var items = components.queryItems ?? []
        items.removeAll { $0.name == "presentation" }
        if let language {
            items.removeAll { $0.name == "lang" }
            items.append(URLQueryItem(name: "lang", value: language.rawValue))
        }
        components.queryItems = items.isEmpty ? nil : items
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
    let clientAccess: Bool
    let visitorID: String
    let webSession: WebPageSession?
    let allowsLocalCatalog: Bool
    let onReference: ((ResearchDocumentTypedLink) -> Void)?
    let onNavigation: ((String) -> Void)?
    let onExternalURL: ((URL) -> Void)?
    let onAuthentication: ((ClientWebAuthenticationMessage.Action) -> Void)?
    @Binding var loadError: String?

    init(
        url: URL,
        syncServerCookies: Bool,
        enforceEmbeddedPresentation: Bool = false,
        serverOrigin: URL? = nil,
        sessionToken: String = "",
        servicePort: String = "",
        clientAccess: Bool = false,
        visitorID: String = "",
        webSession: WebPageSession? = nil,
        allowsLocalCatalog: Bool = false,
        onReference: ((ResearchDocumentTypedLink) -> Void)? = nil,
        onNavigation: ((String) -> Void)? = nil,
        onExternalURL: ((URL) -> Void)? = nil,
        onAuthentication: ((
            ClientWebAuthenticationMessage.Action
        ) -> Void)? = nil,
        loadError: Binding<String?> = .constant(nil)
    ) {
        self.url = url
        self.syncServerCookies = syncServerCookies
        self.enforceEmbeddedPresentation = enforceEmbeddedPresentation
        self.serverOrigin = serverOrigin
        self.sessionToken = sessionToken
        self.servicePort = servicePort
        self.clientAccess = clientAccess
        self.visitorID = visitorID
        self.webSession = webSession
        self.allowsLocalCatalog = allowsLocalCatalog
        self.onReference = onReference
        self.onNavigation = onNavigation
        self.onExternalURL = onExternalURL
        self.onAuthentication = onAuthentication
        _loadError = loadError
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(
            loadError: $loadError,
            enforceEmbeddedPresentation: enforceEmbeddedPresentation,
            serverOrigin: serverOrigin,
            onReference: onReference,
            onNavigation: onNavigation,
            onExternalURL: onExternalURL,
            onAuthentication: onAuthentication
        )
    }

    private func makeWebView(context: Context) -> WKWebView {
        if let existing = webSession?.webView {
            existing.removeFromSuperview()
            existing.navigationDelegate = context.coordinator
            existing.uiDelegate = context.coordinator
            existing.configuration.userContentController.removeScriptMessageHandler(
                forName: ResearchDocumentWebReferenceMessage.handlerName
            )
            existing.configuration.userContentController.removeScriptMessageHandler(
                forName: ResearchDocumentWebNavigationMessage.handlerName
            )
            existing.configuration.userContentController.removeScriptMessageHandler(
                forName: ClientWebAuthenticationMessage.handlerName
            )
            #if os(macOS)
            existing.configuration.userContentController.removeScriptMessageHandler(
                forName: ClientLocalCatalogBridgeContract.messageName
            )
            existing.configuration.userContentController.removeScriptMessageHandler(
                forName: LocalRunBridgeContract.messageName
            )
            if allowsLocalCatalog {
                existing.configuration.userContentController.addScriptMessageHandler(
                    ClientLocalCatalogBridge(),
                    contentWorld: .page,
                    name: ClientLocalCatalogBridgeContract.messageName
                )
                existing.configuration.userContentController.addScriptMessageHandler(
                    LocalRunBridge(),
                    contentWorld: .page,
                    name: LocalRunBridgeContract.messageName
                )
            }
            #endif
            if enforceEmbeddedPresentation {
                existing.configuration.userContentController.add(
                    context.coordinator,
                    name: ResearchDocumentWebReferenceMessage.handlerName
                )
                existing.configuration.userContentController.add(
                    context.coordinator,
                    name: ResearchDocumentWebNavigationMessage.handlerName
                )
            }
            existing.configuration.userContentController.add(
                context.coordinator,
                name: ClientWebAuthenticationMessage.handlerName
            )
            Task { await prepareAndLoad(existing) }
            return existing
        }
        let configuration = WKWebViewConfiguration()
        #if os(macOS)
        if allowsLocalCatalog {
            configuration.userContentController.addScriptMessageHandler(
                ClientLocalCatalogBridge(),
                contentWorld: .page,
                name: ClientLocalCatalogBridgeContract.messageName
            )
            configuration.userContentController.addScriptMessageHandler(
                LocalRunBridge(),
                contentWorld: .page,
                name: LocalRunBridgeContract.messageName
            )
        }
        #endif
        if enforceEmbeddedPresentation {
            configuration.userContentController.add(
                context.coordinator,
                name: ResearchDocumentWebReferenceMessage.handlerName
            )
            configuration.userContentController.add(
                context.coordinator,
                name: ResearchDocumentWebNavigationMessage.handlerName
            )
        }
        configuration.userContentController.add(
            context.coordinator,
            name: ClientWebAuthenticationMessage.handlerName
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
        webView.uiDelegate = context.coordinator
        webSession?.webView = webView
        Task { await prepareAndLoad(webView) }
        return webView
    }

    #if os(iOS)
    func makeUIView(context: Context) -> WKWebView { makeWebView(context: context) }
    func updateUIView(_ webView: WKWebView, context: Context) {
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        Task { await prepareAndLoad(webView) }
    }
    #else
    func makeNSView(context: Context) -> WKWebView { makeWebView(context: context) }
    func updateNSView(_ webView: WKWebView, context: Context) {
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
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
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: ClientWebAuthenticationMessage.handlerName
        )
        #if os(macOS)
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: ClientLocalCatalogBridgeContract.messageName
        )
        webView.configuration.userContentController.removeScriptMessageHandler(
            forName: LocalRunBridgeContract.messageName
        )
        #endif
        webView.navigationDelegate = nil
        webView.uiDelegate = nil
    }

    /// 先把共享 HTTPCookieStorage 里的 cookie 灌进 WebView，再加载目标页。
    @MainActor
    private func prepareAndLoad(_ webView: WKWebView) async {
        let needsNavigation = webSession?.loadedURL != url
            || webSession?.loadedToken != sessionToken
            || webSession?.loadedServicePort != servicePort
            || webSession?.loadedVisitorID != visitorID
        guard needsNavigation else { return }
        webSession?.loadedURL = url
        webSession?.loadedToken = sessionToken
        webSession?.loadedServicePort = servicePort
        webSession?.loadedVisitorID = visitorID
        let controller = webView.configuration.userContentController
        controller.removeAllUserScripts()
        let sessionScript: String
        if !sessionToken.isEmpty,
           let data = try? JSONEncoder().encode(sessionToken),
           let literal = String(data: data, encoding: .utf8) {
            sessionScript = "localStorage.setItem('ft-session', \(literal));"
        } else {
            sessionScript = "localStorage.removeItem('ft-session');"
        }
        controller.addUserScript(WKUserScript(
            source: sessionScript,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))
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
        // Manager-backed pages such as sqlite-web are ordinary navigations,
        // so their requests cannot read the SPA localStorage token.  Project
        // the already-authenticated Manager token into a scoped cookie before
        // the first load; the Manager accepts the same token via Authorization
        // or this scoped session cookie.
        if !sessionToken.isEmpty {
            let managerURL = serverOrigin ?? url
            if let host = managerURL.host,
               let cookie = HTTPCookie(properties: [
                   .domain: host,
                   .path: "/",
                   .name: "ft-manager-session",
                   .value: sessionToken,
                   .secure: managerURL.scheme == "https" ? "TRUE" : "FALSE",
               ]) {
                await webView.configuration.websiteDataStore.httpCookieStore.setCookie(cookie)
            }
        }

        var request = URLRequest(url: url)
        if clientAccess {
            request.setValue(
                "ftclient",
                forHTTPHeaderField: "X-FactorTester-Client-Access"
            )
            if VisitorIdentityStore.isValid(visitorID) {
                request.setValue(
                    visitorID,
                    forHTTPHeaderField: "X-FactorTester-Visitor-ID"
                )
            }
        }
        webView.load(request)
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate,
        WKScriptMessageHandler {
        @Binding private var loadError: String?
        private let enforceEmbeddedPresentation: Bool
        private let serverOrigin: URL?
        private let onReference: ((ResearchDocumentTypedLink) -> Void)?
        private let onNavigation: ((String) -> Void)?
        private let onExternalURL: ((URL) -> Void)?
        private let onAuthentication: ((
            ClientWebAuthenticationMessage.Action
        ) -> Void)?

        init(
            loadError: Binding<String?>,
            enforceEmbeddedPresentation: Bool,
            serverOrigin: URL?,
            onReference: ((ResearchDocumentTypedLink) -> Void)?,
            onNavigation: ((String) -> Void)?,
            onExternalURL: ((URL) -> Void)?,
            onAuthentication: ((
                ClientWebAuthenticationMessage.Action
            ) -> Void)?
        ) {
            _loadError = loadError
            self.enforceEmbeddedPresentation = enforceEmbeddedPresentation
            self.serverOrigin = serverOrigin
            self.onReference = onReference
            self.onNavigation = onNavigation
            self.onExternalURL = onExternalURL
            self.onAuthentication = onAuthentication
        }

        func userContentController(
            _ userContentController: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            if message.name == ClientWebAuthenticationMessage.handlerName,
               let action = ClientWebAuthenticationMessage.action(
                   from: message.body
               ) {
                DispatchQueue.main.async { [weak self] in
                    self?.onAuthentication?(action)
                }
                return
            }
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

        #if os(macOS)
        /// Keep file-backed run inputs on the shared Web contract while using
        /// the native macOS picker inside the embedded client.
        func webView(
            _ webView: WKWebView,
            runOpenPanelWith parameters: WKOpenPanelParameters,
            initiatedByFrame frame: WKFrameInfo,
            completionHandler: @escaping ([URL]?) -> Void
        ) {
            let panel = NSOpenPanel()
            panel.canChooseFiles = true
            panel.canChooseDirectories = parameters.allowsDirectories
            panel.allowsMultipleSelection = parameters.allowsMultipleSelection
            panel.resolvesAliases = true
            let finish: (NSApplication.ModalResponse) -> Void = { response in
                completionHandler(response == .OK ? panel.urls : nil)
            }
            if let window = webView.window {
                panel.beginSheetModal(for: window, completionHandler: finish)
            } else {
                panel.begin(completionHandler: finish)
            }
        }
        #endif

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
