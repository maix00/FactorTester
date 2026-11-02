"""New clients prefer renamed assets while existing releases stay installable."""
from pathlib import Path
import subprocess


def test_release_asset_selection_prefers_new_name_and_rejects_ambiguity(tmp_path):
    root = Path(__file__).resolve().parents[2]
    source = tmp_path / 'main.swift'
    source.write_text('''import Foundation
func release(_ names: [String]) throws -> GitHubRelease {
    let assets = names.map { ["name": $0, "browser_download_url": "https://example.test/file", "size": 1] as [String: Any] }
    return try JSONDecoder().decode(GitHubRelease.self, from: JSONSerialization.data(withJSONObject: ["tag_name": "v1", "draft": false, "prerelease": false, "assets": assets]))
}
let legacy = try release(["FactorTester-Client.dmg"])
let mixed = try release(["FactorTester-Client.dmg", "TradeResearch.dmg"])
let duplicate = try release(["TradeResearch.dmg", "TradeResearch.dmg"])
precondition(legacy.installer?.name == "FactorTester-Client.dmg")
precondition(mixed.installer?.name == "TradeResearch.dmg")
precondition(duplicate.installer == nil)
''')
    executable = tmp_path / 'asset-test'
    subprocess.run(['swiftc', str(root / 'apple/Sources/Features/Updates/GitHubReleaseModels.swift'), str(source), '-o', str(executable)], check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True)
