"""Execute the actual Swift session serialization and logout coordinator."""
from pathlib import Path
import subprocess


def test_session_writes_are_deduplicated_and_logout_clears_last(tmp_path):
    root = Path(__file__).resolve().parents[2]
    runner = tmp_path / 'Runner.swift'
    runner.write_text('''import Foundation
@main struct Runner {
  @MainActor static func main() async {
    let coordinator = ClientSessionBridgeCoordinator()
    var events: [String] = []
    var continuation: CheckedContinuation<Void, Never>?
    let first = Task { @MainActor in await coordinator.submit(key: "old", valid: { true }) {
      events.append("start"); await withCheckedContinuation { continuation = $0 }; events.append("finish"); return true
    }}
    while continuation == nil { await Task.yield() }
    let stale = Task { @MainActor in await coordinator.submit(key: "stale", valid: { true }) { events.append("stale"); return true } }
    await Task.yield()
    let logout = Task { @MainActor in await coordinator.invalidateAndClear { events.append("clear") } }
    await Task.yield()
    continuation?.resume()
    _ = await first.value; _ = await stale.value; await logout.value
    precondition(events == ["start", "finish", "clear"], "stale write or wrong order: \\(events)")
    var count = 0
    for key in ["a", "a", "b", "b"] {
      let ok = await coordinator.submit(key: key, valid: { true }) { count += 1; return true }
      precondition(ok)
    }
    precondition(count == 2)
    let denied = await coordinator.submit(key: "c", valid: { false }) { fatalError("invalid write executed") }
    precondition(!denied)
  }
}
''')
    executable = tmp_path / 'coordinator-test'
    subprocess.run(['swiftc', '-parse-as-library', str(root / 'apple/Sources/Features/Auth/ClientSessionBridgeCoordinator.swift'),
                    str(runner), '-o', str(executable)], check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, timeout=15, capture_output=True, text=True)
