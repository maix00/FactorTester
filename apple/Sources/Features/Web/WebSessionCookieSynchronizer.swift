import Foundation
import WebKit

/// Imports the Web shell's HttpOnly Manager session into native clients.
///
/// The WebView remains the owner of the login form and bearer token. Only the
/// server-issued session cookie crosses into URLSession; passwords and Web
/// storage values never cross the JavaScript bridge.
enum WebSessionCookieSynchronizer {
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
            cookieBelongsToHost(cookie, host: host)
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
