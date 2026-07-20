from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
LOCALIZATION = ROOT / "apple/Sources/Localization/AppLanguage.swift"
MIGRATION = (
    ROOT
    / "apple/Sources/Features/Updates/LegacyAppNameMigration.swift"
)


def test_legacy_app_is_retired_only_after_bundle_identity_check(
    tmp_path: Path,
) -> None:
    runner = tmp_path / "Acceptance.swift"
    runner.write_text(
        """
import Foundation

func makeApp(_ url: URL, identifier: String) throws {
    let contents = url.appendingPathComponent("Contents")
    try FileManager.default.createDirectory(
        at: contents,
        withIntermediateDirectories: true
    )
    let plist: [String: Any] = ["CFBundleIdentifier": identifier]
    let data = try PropertyListSerialization.data(
        fromPropertyList: plist,
        format: .xml,
        options: 0
    )
    try data.write(to: contents.appendingPathComponent("Info.plist"))
}

@main
struct Acceptance {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let applications = root.appendingPathComponent("Applications")
        let current = applications.appendingPathComponent("FTClient.app")
        let legacy = applications.appendingPathComponent(
            "FactorTester-Client.app"
        )
        let receipts = root.appendingPathComponent("receipts")
        let developmentBuild = root.appendingPathComponent("FTClient.app")
        try makeApp(current, identifier: "com.gtht.client")
        try makeApp(legacy, identifier: "com.gtht.client")
        try makeApp(developmentBuild, identifier: "com.gtht.client")

        let ignoredDevelopmentBuild = try LegacyAppNameMigration.run(
            applicationsDirectory: applications,
            currentBundleURL: developmentBuild,
            receiptRoot: receipts
        )
        precondition(!ignoredDevelopmentBuild)
        precondition(FileManager.default.fileExists(atPath: legacy.path))

        let migrated = try LegacyAppNameMigration.run(
            applicationsDirectory: applications,
            currentBundleURL: current,
            receiptRoot: receipts
        )
        precondition(migrated)
        precondition(FileManager.default.fileExists(atPath: current.path))
        precondition(!FileManager.default.fileExists(atPath: legacy.path))
        precondition(
            FileManager.default.fileExists(
                atPath: receipts.appendingPathComponent(
                    "app-name-migration.json"
                ).path
            )
        )
        let repeated = try LegacyAppNameMigration.run(
            applicationsDirectory: applications,
            currentBundleURL: current,
            receiptRoot: receipts
        )
        precondition(!repeated)

        try makeApp(legacy, identifier: "example.untrusted")
        do {
            _ = try LegacyAppNameMigration.run(
                applicationsDirectory: applications,
                currentBundleURL: current,
                receiptRoot: receipts
            )
            fatalError("identity mismatch was accepted")
        } catch LegacyAppMigrationError.bundleIdentityMismatch {
            precondition(FileManager.default.fileExists(atPath: legacy.path))
        }
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
            str(MIGRATION),
            str(runner),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [str(executable), str(tmp_path / "state")],
        check=True,
        capture_output=True,
        text=True,
    )
