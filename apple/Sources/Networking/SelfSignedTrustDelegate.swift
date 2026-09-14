import Foundation

/// 放行自签名 TLS 证书。
///
/// 自托管服务器常用自签名证书或局域网 IP，系统默认会拒绝。这里对用户**已配置的
/// 那台主机**接受其服务器证书；其余主机仍走系统默认校验，避免全局降级安全。
final class SelfSignedTrustDelegate: NSObject, URLSessionDelegate, URLSessionTaskDelegate {
    private let allowedHosts: Set<String>?
    private let rejectsRedirects: Bool

    init(
        allowedHosts: Set<String>? = nil,
        rejectsRedirects: Bool = false
    ) {
        self.allowedHosts = allowedHosts
        self.rejectsRedirects = rejectsRedirects
        super.init()
    }

    static func certificatePEM(for endpoint: URL?) -> String {
        guard let endpoint, endpoint.scheme == "https", let host = endpoint.host else { return "" }
        let authority = "https://\(host.lowercased()):\(endpoint.port ?? 443)"
        guard let data = UserDefaults.standard.data(forKey: "cli.trusted-certificate." + authority) else { return "" }
        return "-----BEGIN CERTIFICATE-----\n" + data.base64EncodedString(options: [.lineLength64Characters, .endLineWithLineFeed]) + "\n-----END CERTIFICATE-----\n"
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(rejectsRedirects ? nil : request)
    }

    func urlSession(_ session: URLSession,
                    didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {

        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust else {
            completionHandler(.performDefaultHandling, nil)
            return
        }

        let configuredHost = ServerConfig.shared.host.trimmingCharacters(in: .whitespaces).lowercased()
        let managerHost = ManagerConfig.shared.host.trimmingCharacters(in: .whitespaces).lowercased()
        let challengedHost = challenge.protectionSpace.host.lowercased()

        let configuredHosts = allowedHosts ?? Set(
            [configuredHost, managerHost].filter { !$0.isEmpty }
        )
        if configuredHosts.contains(challengedHost) {
            if let certificate = SecTrustGetCertificateAtIndex(trust, 0) {
                let data = SecCertificateCopyData(certificate) as Data
                let authority = "https://\(challengedHost):\(challenge.protectionSpace.port)"
                UserDefaults.standard.set(data, forKey: "cli.trusted-certificate." + authority)
            }
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            completionHandler(.performDefaultHandling, nil)
        }
    }
}
