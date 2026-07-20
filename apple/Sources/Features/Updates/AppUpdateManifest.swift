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
        let manifest = try JSONDecoder().decode(AppUpdateManifest.self, from: data)
        guard manifest.schemaVersion == 1,
              manifest.channel == expectedChannel,
              manifest.build > 0,
              manifest.dmgURL.scheme == "https",
              manifest.dmgURL.pathExtension == "dmg",
              manifest.sha256.range(
                of: "^[0-9a-f]{64}$", options: .regularExpression
              ) != nil,
              manifest.signature.algorithm == "ecdsa-sha256"
        else { throw AppUpdateError.invalidManifest }
        guard SHA256.hash(data: Data(publicKeyPEM.utf8)).hex
                == manifest.signature.keyID else {
            throw AppUpdateError.manifestSignatureMismatch
        }
        var object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
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
            manifest: manifest, manifestHash: rawHash, source: source
        )
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

private struct SemanticVersion: Comparable {
    let core: [Int]
    let prerelease: [String]

    init?(_ raw: String) {
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
