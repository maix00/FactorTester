import Foundation

extension ClientReleaseController {
    func resolveRelease() async throws -> VerifiedAppUpdate {
        guard let keyURL = Bundle.main.url(
            forResource: "trusted-release-public", withExtension: "pem"
        ) else { throw AppUpdateError.invalidManifest }
        let key = try String(contentsOf: keyURL, encoding: .utf8)
        let server = ServerConfig.shared.url(
            forPath: "/api/client/releases/\(channel).json"
        )
        let github = URL(
            string: "https://github.com/maix00/FactorTester-Client/releases/latest/download/\(channel).json"
        )!
        var failures: [String] = []
        for (source, url) in [("server", server), ("github", github)] {
            guard let url else { continue }
            do {
                var request = URLRequest(url: url)
                request.timeoutInterval = 15
                request.setValue("application/json", forHTTPHeaderField: "Accept")
                let (data, response) = try await URLSession.shared.data(for: request)
                try requireSuccess(response)
                let etag = (response as? HTTPURLResponse)?
                    .value(forHTTPHeaderField: "ETag")
                return try AppUpdateManifestVerifier.verify(
                    data: data, expectedETag: etag,
                    publicKeyPEM: key, expectedChannel: channel,
                    source: source
                )
            } catch {
                failures.append("\(source): \(error.localizedDescription)")
            }
        }
        throw AppUpdateError.server(
            L10n.text("没有可用的可信签名更新清单。")
                + " " + failures.joined(separator: "; ")
        )
    }

    func requireSuccess(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse,
              (200..<300).contains(http.statusCode) else {
            throw AppUpdateError.server(L10n.text("更新清单或 DMG 请求失败。"))
        }
    }
}
