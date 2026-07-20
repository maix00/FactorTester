from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
STORE = (
    ROOT
    / "apple/Sources/Features/Updates/AppUpdateStore.swift"
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
