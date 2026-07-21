import CryptoKit
import Foundation

struct AppUpdateManifest: Decodable {
    let schemaVersion: Int
    let version: String
    let build: Int
    let channel: String
    let dmgURL: URL
    let sha256: String
    let minimumClient: String
    let mandatory: Bool
    let publishedAt: String
    let signature: Signature

    struct Signature: Decodable {
        let algorithm: String
        let keyID: String
        let value: String
        enum CodingKeys: String, CodingKey {
            case algorithm
            case keyID = "key_id"
            case value
        }
    }
    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case version, build, channel
        case dmgURL = "dmg_url"
        case sha256
        case minimumClient = "minimum_client"
        case mandatory
        case publishedAt = "published_at"
        case signature
    }
}

struct VerifiedAppUpdate {
    let manifest: AppUpdateManifest
    let manifestHash: String
    let source: String
}

enum AppUpdateManifestVerifier {
    static func verify(
        data: Data,
        expectedETag: String?,
        publicKeyPEM: String,
        expectedChannel: String,
        source: String
    ) throws -> VerifiedAppUpdate {
        guard data.count <= 64 * 1024 else {
            throw AppUpdateError.invalidManifest
        }
        let rawHash = SHA256.hash(data: data).hex
        if let expectedETag, !expectedETag.isEmpty,
           expectedETag.trimmingCharacters(in: CharacterSet(charactersIn: "\""))
            != rawHash {
            throw AppUpdateError.manifestDigestMismatch
        }
        guard let rawObject = try JSONSerialization.jsonObject(
            with: data
        ) as? [String: Any],
              Set(rawObject.keys) == Set([
                "schema_version", "version", "build", "channel", "dmg_url",
                "sha256", "minimum_client", "mandatory", "published_at",
                "signature",
              ]),
              let rawSignature = rawObject["signature"] as? [String: Any],
              Set(rawSignature.keys) == Set(["algorithm", "key_id", "value"])
        else { throw AppUpdateError.invalidManifest }
        let manifest = try JSONDecoder().decode(AppUpdateManifest.self, from: data)
        guard manifest.schemaVersion == 1,
              manifest.channel == expectedChannel,
              manifest.build > 0,
              TrustedUpdateURL.accepts(manifest.dmgURL),
              UpdateContract.isDMGURL(manifest.dmgURL),
              UpdateContract.isSemanticVersion(manifest.version),
              UpdateContract.isSemanticVersion(manifest.minimumClient),
              UpdateContract.isPublishedAt(manifest.publishedAt),
              manifest.sha256.range(
                of: "^[0-9a-f]{64}$", options: .regularExpression
              ) != nil,
              manifest.signature.algorithm == "ecdsa-sha256"
        else { throw AppUpdateError.invalidManifest }
        guard SHA256.hash(data: Data(publicKeyPEM.utf8)).hex
                == manifest.signature.keyID else {
            throw AppUpdateError.manifestSignatureMismatch
        }
        var object: [String: Any]? = rawObject
        object?.removeValue(forKey: "signature")
        guard let object,
              let signature = Data(base64Encoded: manifest.signature.value)
        else { throw AppUpdateError.invalidManifest }
        let payload = try JSONSerialization.data(
            withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes]
        )
        let key = try P256.Signing.PublicKey(pemRepresentation: publicKeyPEM)
        let value = try P256.Signing.ECDSASignature(derRepresentation: signature)
        guard key.isValidSignature(value, for: payload) else {
            throw AppUpdateError.manifestSignatureMismatch
        }
        return VerifiedAppUpdate(
            manifest: manifest,
            manifestHash: SHA256.hash(data: payload).hex,
            source: source
        )
    }

}

enum UpdateContract {
    private static let semverIdentifier =
        "(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    private static let semverPattern =
        "^(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)\\."
        + "(?:0|[1-9][0-9]*)"
        + "(?:-\(semverIdentifier)(?:\\.\(semverIdentifier))*)?"
        + "(?:\\+[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?$"
    private static let publishedAtPattern =
        "^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
        + "[0-2][0-9]:[0-5][0-9]:[0-5][0-9]"
        + "(?:\\.[0-9]{1,6})?"
        + "(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"

    static func isSemanticVersion(_ value: String) -> Bool {
        value.range(of: semverPattern, options: .regularExpression) != nil
    }

    static func isPublishedAt(_ value: String) -> Bool {
        guard value.range(
            of: publishedAtPattern, options: .regularExpression
        ) != nil else { return false }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if formatter.date(from: value) != nil { return true }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value) != nil
    }

    static func isDMGURL(_ url: URL) -> Bool {
        TrustedUpdateURL.accepts(url) && url.path.hasSuffix(".dmg")
    }
}

enum TrustedUpdateURL {
    private static let loopbackHosts = Set(["127.0.0.1", "::1", "localhost"])

    static func accepts(_ url: URL) -> Bool {
        guard let scheme = url.scheme?.lowercased(),
              let host = url.host?.lowercased(),
              url.user == nil,
              url.password == nil else { return false }
        return scheme == "https" || (scheme == "http" && loopbackHosts.contains(host))
    }

    static func sameOrigin(_ lhs: URL, _ rhs: URL) -> Bool {
        guard accepts(lhs), accepts(rhs) else { return false }
        return lhs.scheme?.lowercased() == rhs.scheme?.lowercased()
            && lhs.host?.lowercased() == rhs.host?.lowercased()
            && effectivePort(lhs) == effectivePort(rhs)
    }

    private static func effectivePort(_ url: URL) -> Int? {
        if let port = url.port { return port }
        return url.scheme?.lowercased() == "https" ? 443 : 80
    }
}

enum VersionOrder {
    static func isNewer(_ candidate: String, than installed: String) -> Bool {
        guard let left = SemanticVersion(candidate),
              let right = SemanticVersion(installed) else { return false }
        return left > right
    }

    static func isNewerRelease(
        version: String,
        build: Int,
        thanVersion installedVersion: String,
        build installedBuild: Int
    ) -> Bool {
        if isNewer(version, than: installedVersion) { return true }
        return version == installedVersion && build > installedBuild
    }
}

enum ClientCompatibility {
    static func accepts(installed: String, minimum: String) -> Bool {
        guard UpdateContract.isSemanticVersion(installed),
              UpdateContract.isSemanticVersion(minimum) else { return false }
        return !VersionOrder.isNewer(minimum, than: installed)
    }
}

private struct SemanticVersion: Comparable {
    let core: [Int]
    let prerelease: [String]

    init?(_ raw: String) {
        guard UpdateContract.isSemanticVersion(raw) else { return nil }
        let withoutBuild = raw.split(separator: "+", maxSplits: 1)[0]
        let pieces = withoutBuild.split(
            separator: "-", maxSplits: 1, omittingEmptySubsequences: false
        )
        let numbers = pieces[0].split(separator: ".").compactMap { Int($0) }
        guard numbers.count == 3 else { return nil }
        core = numbers
        prerelease = pieces.count == 2
            ? pieces[1].split(separator: ".").map(String.init) : []
    }

    static func < (lhs: Self, rhs: Self) -> Bool {
        if lhs.core != rhs.core {
            return lhs.core.lexicographicallyPrecedes(rhs.core)
        }
        if lhs.prerelease.isEmpty { return false }
        if rhs.prerelease.isEmpty { return true }
        for (left, right) in zip(lhs.prerelease, rhs.prerelease) where left != right {
            if let l = Int(left), let r = Int(right) { return l < r }
            if Int(left) != nil { return true }
            if Int(right) != nil { return false }
            return left < right
        }
        return lhs.prerelease.count < rhs.prerelease.count
    }
}

private extension SHA256.Digest {
    var hex: String { map { String(format: "%02x", $0) }.joined() }
}
