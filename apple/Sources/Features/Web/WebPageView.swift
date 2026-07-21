import SwiftUI
import WebKit

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
    @EnvironmentObject private var session: SessionStore
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
                            reloadID = UUID()
                        }
                        Button("登录 / 注册") { showLogin = true }
                            .buttonStyle(.borderedProminent)
                    }
                }
                .padding(30)
            } else if let rawURL = ServerConfig.shared.url(forPath: path),
                      let url = EmbeddedPresentationURL.add(to: rawURL) {
                WebViewRepresentable(
                    url: url,
                    syncServerCookies: true,
                    enforceEmbeddedPresentation: true,
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
}

enum EmbeddedPresentationURL {
    static func add(to url: URL) -> URL? {
        guard var components = URLComponents(
            url: url,
            resolvingAgainstBaseURL: false
        ) else { return nil }
        var items = components.queryItems ?? []
        items.removeAll { $0.name == "presentation" }
        items.append(URLQueryItem(name: "presentation", value: "embedded"))
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
    @Binding var loadError: String?

    init(
        url: URL,
        syncServerCookies: Bool,
        enforceEmbeddedPresentation: Bool = false,
        loadError: Binding<String?> = .constant(nil)
    ) {
        self.url = url
        self.syncServerCookies = syncServerCookies
        self.enforceEmbeddedPresentation = enforceEmbeddedPresentation
        _loadError = loadError
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(
            loadError: $loadError,
            enforceEmbeddedPresentation: enforceEmbeddedPresentation
        )
    }

    private func makeWebView(context: Context) -> WKWebView {
        let webView = WKWebView(frame: .zero)
        webView.navigationDelegate = context.coordinator
        Task { await prepareAndLoad(webView) }
        return webView
    }

    #if os(iOS)
    func makeUIView(context: Context) -> WKWebView { makeWebView(context: context) }
    func updateUIView(_ webView: WKWebView, context: Context) {}
    #else
    func makeNSView(context: Context) -> WKWebView { makeWebView(context: context) }
    func updateNSView(_ webView: WKWebView, context: Context) {}
    #endif

    /// 先把共享 HTTPCookieStorage 里的 cookie 灌进 WebView，再加载目标页。
    @MainActor
    private func prepareAndLoad(_ webView: WKWebView) async {
        if syncServerCookies, let host = ServerConfig.shared.baseURL?.host {
            let store = webView.configuration.websiteDataStore.httpCookieStore
            let cookies = (HTTPCookieStorage.shared.cookies ?? [])
                .filter { $0.domain.contains(host) }
            for cookie in cookies { await store.setCookie(cookie) }
        }

        webView.load(URLRequest(url: url))
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        @Binding private var loadError: String?
        private let enforceEmbeddedPresentation: Bool

        init(
            loadError: Binding<String?>,
            enforceEmbeddedPresentation: Bool
        ) {
            _loadError = loadError
            self.enforceEmbeddedPresentation = enforceEmbeddedPresentation
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard enforceEmbeddedPresentation,
                  navigationAction.targetFrame?.isMainFrame != false,
                  let destination = navigationAction.request.url,
                  let origin = ServerConfig.shared.baseURL,
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
            let configuredHost = ServerConfig.shared.host.trimmingCharacters(in: .whitespaces).lowercased()
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
