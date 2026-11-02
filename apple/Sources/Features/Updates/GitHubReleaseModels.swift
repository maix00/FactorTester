import Foundation

struct GitHubRelease: Decodable {
    let tagName: String
    let draft: Bool
    let prerelease: Bool
    let assets: [GitHubReleaseAsset]

    enum CodingKeys: String, CodingKey {
        case tagName = "tag_name"
        case draft, prerelease, assets
    }

    var version: String {
        tagName.hasPrefix("v") ? String(tagName.dropFirst()) : tagName
    }

    var installer: GitHubReleaseAsset? {
        let current = assets.filter { $0.name == "TradeResearch.dmg" }
        if !current.isEmpty { return current.count == 1 ? current[0] : nil }
        let legacy = assets.filter { $0.name == "FactorTester-Client.dmg" }
        return legacy.count == 1 ? legacy[0] : nil
    }
}

struct GitHubReleaseAsset: Decodable {
    let name: String
    let browserDownloadURL: URL
    let size: Int64
    let digest: String?

    enum CodingKeys: String, CodingKey {
        case name
        case browserDownloadURL = "browser_download_url"
        case size, digest
    }

    var sha256: String? {
        guard let digest, digest.hasPrefix("sha256:") else { return nil }
        return String(digest.dropFirst("sha256:".count))
    }
}
