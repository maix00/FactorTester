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

    var body: some View {
        if let url = ServerConfig.shared.url(forPath: path) {
            WebViewRepresentable(url: url, syncServerCookies: true)
                .ignoresSafeArea(edges: .bottom)
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

    func makeCoordinator() -> Coordinator { Coordinator() }

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
