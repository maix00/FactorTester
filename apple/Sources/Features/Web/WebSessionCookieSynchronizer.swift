import Foundation
import WebKit

/// Imports the Web shell's HttpOnly Manager session into native clients.
///
/// The WebView remains the owner of the login form and bearer token. Only the
/// server-issued session cookie crosses into URLSession; passwords and Web
/// storage values never cross the JavaScript bridge.
enum WebSessionCookieSynchronizer {
    static func makeSessionCookie(token: String, endpoint: URL) -> HTTPCookie? {
        guard !token.isEmpty, let host = endpoint.host,
              let scheme = endpoint.scheme?.lowercased(), ["http", "https"].contains(scheme) else { return nil }
        var properties: [HTTPCookiePropertyKey: Any] = [
            .domain: host, .path: "/", .name: "ft-manager-session", .value: token,
        ]
        // Foundation interprets the *presence* of .secure as true, even if
        // its value is the string "FALSE". Omit the key for an HTTP LAN.
        if scheme == "https" { properties[.secure] = "TRUE" }
        return HTTPCookie(properties: properties)
    }

    @MainActor
    static func importManagerSession(
        from webView: WKWebView,
        endpoint: URL?
    ) async {
        let cookieStore = webView.configuration.websiteDataStore.httpCookieStore
        let cookies = await withCheckedContinuation { continuation in
            cookieStore.getAllCookies { cookies in
                continuation.resume(returning: cookies)
            }
        }
        let origin = endpoint ?? webView.url
        guard let host = origin?.host?.lowercased() else { return }
        let matching = cookies.filter { cookie in
            cookie.name == "ft-manager-session" && cookieBelongsToHost(cookie, host: host)
        }
        for cookie in matching {
            HTTPCookieStorage.shared.setCookie(cookie)
        }
        if let session = matching.first(where: {
            $0.name == "ft-manager-session" && !$0.value.isEmpty
        }) {
            ManagerSessionTokenStore.save(session.value, for: origin)
        }
    }

    /// Cookie domains do not include ports. Remove the target host's old
    /// session before loading a different endpoint on that host; the target's
    /// endpoint-scoped Keychain token is kept separately.
    @MainActor
    static func clearManagerSession(for endpoint: URL, webView: WKWebView?) async {
        guard let host = endpoint.host?.lowercased() else { return }
        func belongs(_ cookie: HTTPCookie) -> Bool {
            cookie.name == "ft-manager-session" && cookieBelongsToHost(cookie, host: host)
        }
        for cookie in HTTPCookieStorage.shared.cookies ?? [] where belongs(cookie) {
            HTTPCookieStorage.shared.deleteCookie(cookie)
        }
        if let store = webView?.configuration.websiteDataStore.httpCookieStore {
            let cookies = await withCheckedContinuation { continuation in
                store.getAllCookies { continuation.resume(returning: $0) }
            }
            for cookie in cookies where belongs(cookie) { await store.deleteCookie(cookie) }
        }
    }

    private static func cookieBelongsToHost(
        _ cookie: HTTPCookie,
        host: String
    ) -> Bool {
        let domain = cookie.domain
            .trimmingCharacters(in: CharacterSet(charactersIn: "."))
            .lowercased()
        return domain == host || host.hasSuffix(".\(domain)")
    }
}
