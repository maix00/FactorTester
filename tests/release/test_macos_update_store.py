from pathlib import Path
import hashlib
import json
import subprocess

from script.release.update_manifest import create_update_manifest

ROOT = Path(__file__).resolve().parents[2]
STORE = (
    ROOT
    / "apple/Sources/Features/Updates/AppUpdateStore.swift"
)
LOCALIZATION = ROOT / "apple/Sources/Localization/AppLanguage.swift"
MANIFEST = (
    ROOT / "apple/Sources/Features/Updates/AppUpdateManifest.swift"
)


def test_verified_installer_receipt_retains_previous_for_rollback(
    tmp_path: Path,
) -> None:
    runner = tmp_path / "Acceptance.swift"
    runner.write_text(
        """
import Foundation

@main
struct Acceptance {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let store = AppUpdateStore(root: root)
        for version in ["1.0.0", "1.1.0", "1.2.0"] {
            let source = root.deletingLastPathComponent()
                .appendingPathComponent("source-\\(version).dmg")
            try Data(version.utf8).write(to: source)
            _ = try store.save(
                temporaryURL: source,
                version: version,
                expectedSHA256: try AppUpdateStore.sha256(source)
            )
        }
        guard let previous = store.previousInstaller(
            excluding: ["1.2.0"]
        ) else {
            fatalError("missing rollback installer")
        }
        precondition(previous.lastPathComponent.contains("1.1.0"))
        let receipt = try Data(
            contentsOf: root.appendingPathComponent("receipt.json")
        )
        let decoded = try JSONDecoder().decode(
            AppUpdateReceipt.self,
            from: receipt
        )
        precondition(decoded.installers.count == 2)
        precondition(
            !FileManager.default.fileExists(
                atPath: root.appendingPathComponent(
                    "FactorTester-Client-1.0.0.dmg"
                ).path
            )
        )
    }
}
""",
        encoding="utf-8",
    )
    executable = tmp_path / "acceptance"
    subprocess.run(
        [
            "swiftc",
            str(LOCALIZATION),
            str(STORE),
            str(runner),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [str(executable), str(tmp_path / "updates")],
        check=True,
        capture_output=True,
        text=True,
    )


def test_swift_accepts_server_signed_update_manifest(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    subprocess.run(
        [
            "openssl", "ecparam", "-name", "prime256v1",
            "-genkey", "-noout", "-out", str(private),
        ],
        check=True,
    )
    subprocess.run(
        [
            "openssl", "ec", "-in", str(private),
            "-pubout", "-out", str(public),
        ],
        check=True,
        capture_output=True,
    )
    dmg = tmp_path / "FactorTester-Client.dmg"
    dmg.write_bytes(b"dmg")
    value = create_update_manifest(
        version="1.2.0", build=12, channel="stable", dmg=dmg,
        dmg_url="https://example.test/FactorTester-Client.dmg",
        minimum_client="1.0.0", mandatory=False,
        published_at="2026-07-20T12:00:00Z",
        private_key=private, public_key=public,
    )
    manifest = tmp_path / "stable.json"
    manifest.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    )
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    runner = tmp_path / "Verify.swift"
    runner.write_text(
        """
import Foundation
@main struct Verify {
  static func main() throws {
    let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
    let key = try String(contentsOfFile: CommandLine.arguments[2])
    let value = try AppUpdateManifestVerifier.verify(
      data: data, expectedETag: CommandLine.arguments[3],
      publicKeyPEM: key, expectedChannel: "stable", source: "test"
    )
    precondition(value.manifest.version == "1.2.0")
    precondition(value.manifest.build == 12)
  }
}
"""
    )
    executable = tmp_path / "verify"
    subprocess.run(
        [
            "swiftc", str(LOCALIZATION), str(STORE), str(MANIFEST),
            str(runner), "-o", str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [str(executable), str(manifest), str(public), digest],
        check=True,
        capture_output=True,
        text=True,
    )
