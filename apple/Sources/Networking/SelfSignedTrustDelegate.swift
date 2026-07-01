import Foundation

/// 放行自签名 TLS 证书。
///
/// 自托管服务器常用自签名证书或局域网 IP，系统默认会拒绝。这里对用户**已配置的
/// 那台主机**接受其服务器证书；其余主机仍走系统默认校验，避免全局降级安全。
final class SelfSignedTrustDelegate: NSObject, URLSessionDelegate {

    func urlSession(_ session: URLSession,
                    didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {

        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust else {
            completionHandler(.performDefaultHandling, nil)
            return
        }

        let configuredHost = ServerConfig.shared.host.trimmingCharacters(in: .whitespaces).lowercased()
        let challengedHost = challenge.protectionSpace.host.lowercased()

        if !configuredHost.isEmpty && challengedHost == configuredHost {
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            completionHandler(.performDefaultHandling, nil)
        }
    }
}
