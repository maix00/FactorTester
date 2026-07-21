import Foundation

extension ClientReleaseController {
    func resolveRelease() async throws -> VerifiedAppUpdate {
        let isBeta = channel == "beta"
        let keyName = isBeta
            ? "trusted-beta-release-public" : "trusted-release-public"
        guard let keyURL = Bundle.main.url(
            forResource: keyName, withExtension: "pem"
        ) else { throw AppUpdateError.invalidManifest }
        let key = try String(contentsOf: keyURL, encoding: .utf8)
        let server = ServerConfig.shared.url(
            forPath: "/api/client/releases/\(channel).json"
        )
        let github = URL(
            string: "https://github.com/maix00/FactorTester-Client/releases/latest/download/\(channel).json"
        )!
        let sources: [(String, URL?)] = isBeta
            ? [("server", server)] : [("github", github)]
        var failures: [String] = []
        for (source, url) in sources {
            guard let url else { continue }
            do {
                var request = URLRequest(url: url)
                request.cachePolicy = .reloadIgnoringLocalCacheData
                request.timeoutInterval = 15
                request.setValue("application/json", forHTTPHeaderField: "Accept")
                let (data, response) = try await URLSession.shared.data(for: request)
                try requireSuccess(response)
                guard let finalURL = response.url,
                      TrustedUpdateURL.accepts(finalURL),
                      !isBeta || TrustedUpdateURL.sameOrigin(finalURL, url)
                else { throw AppUpdateError.invalidManifest }
                let etag = source == "server"
                    ? (response as? HTTPURLResponse)?
                        .value(forHTTPHeaderField: "ETag")
                    : nil
                let update = try AppUpdateManifestVerifier.verify(
                    data: data,
                    expectedETag: etag,
                    publicKeyPEM: key, expectedChannel: channel,
                    source: source
                )
                guard !isBeta || TrustedUpdateURL.sameOrigin(
                    update.manifest.dmgURL, finalURL
                ) else { throw AppUpdateError.invalidManifest }
                guard ClientCompatibility.accepts(
                    installed: installedVersion,
                    minimum: update.manifest.minimumClient
                ) else { throw AppUpdateError.incompatibleClient }
                return update
            } catch {
                failures.append("\(source): \(error.localizedDescription)")
            }
        }
        throw AppUpdateError.server(
            L10n.text("当前渠道的权威更新源不可用。")
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
