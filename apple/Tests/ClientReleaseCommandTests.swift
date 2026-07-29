import XCTest
@testable import FTClient

#if os(macOS)
import Darwin
#endif

final class ClientReleaseCommandTests: XCTestCase {
    func testUpdateStatusRootHonorsSharedClientRootOverride() {
        let configured = "/tmp/factortester-client-test-root"
        let fallback = URL(fileURLWithPath: "/tmp/application-support")

        XCTAssertEqual(
            AppUpdateStatusStore.rootURL(
                environment: [
                    AppUpdateStatusStore.clientRootEnvironmentKey: configured
                ],
                applicationSupportURL: fallback
            ).path,
            configured
        )
        XCTAssertEqual(
            AppUpdateStatusStore.rootURL(
                environment: [:],
                applicationSupportURL: fallback
            ).path,
            "/tmp/application-support/FactorTester-Debug"
        )
    }

    func testDrainsLargeJSONResponseWithoutPipeDeadlock() async throws {
        let rows = try await ReleaseCommand.runArray(
            [
                "-c",
                "import json; print(json.dumps([{'value': 'x' * 70000}]))",
            ],
            executable: "/usr/bin/python3"
        )

        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows[0].string("value").count, 70_000)
    }

    func testDrainsLargeStandardErrorWithoutPipeDeadlock() async throws {
        do {
            _ = try await ReleaseCommand.runArray(
                [
                    "-c",
                    "import sys; sys.stderr.write('x' * 70000); sys.exit(7)",
                ],
                executable: "/usr/bin/python3"
            )
            XCTFail("Expected the command to fail")
        } catch ReleaseCommandError.failed(let detail) {
            XCTAssertEqual(detail.count, 70_000)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testTimeoutTerminatesChildAndReturnsChineseError() async throws {
        let pidURL = temporaryPIDURL()
        defer { try? FileManager.default.removeItem(at: pidURL) }

        do {
            _ = try await ReleaseCommand.runArray(
                sleepingCommand(pidURL: pidURL),
                executable: "/usr/bin/python3",
                timeout: .milliseconds(150)
            )
            XCTFail("Expected the command to time out")
        } catch ReleaseCommandError.timedOut {
            XCTAssertEqual(
                ReleaseCommandError.timedOut.localizedDescription,
                "客户端命令执行超时，已终止后台进程。"
            )
        } catch {
            XCTFail("Unexpected error: \(error)")
        }

        let pid = try readPID(from: pidURL)
        try await assertProcessExited(pid)
    }

    func testTaskCancellationTerminatesChild() async throws {
        let pidURL = temporaryPIDURL()
        defer { try? FileManager.default.removeItem(at: pidURL) }
        let task = Task {
            try await ReleaseCommand.runArray(
                sleepingCommand(pidURL: pidURL),
                executable: "/usr/bin/python3",
                timeout: .seconds(10)
            )
        }

        try await waitForPIDFile(pidURL)
        let pid = try readPID(from: pidURL)
        task.cancel()
        do {
            _ = try await task.value
            XCTFail("Expected cancellation")
        } catch is CancellationError {
            // Expected.
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
        try await assertProcessExited(pid)
    }

    private func sleepingCommand(pidURL: URL) -> [String] {
        [
            "-c",
            "import os, pathlib, sys, time; "
                + "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
                + "time.sleep(30); print('[]')",
            pidURL.path,
        ]
    }

    private func temporaryPIDURL() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("ftclient-command-\(UUID().uuidString).pid")
    }

    private func waitForPIDFile(_ url: URL) async throws {
        for _ in 0..<100 {
            if FileManager.default.fileExists(atPath: url.path) { return }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("Child process did not write its PID")
        throw TestFailure.pidMissing
    }

    private func readPID(from url: URL) throws -> pid_t {
        let text = try String(contentsOf: url, encoding: .utf8)
        guard let pid = pid_t(text) else { throw TestFailure.invalidPID }
        return pid
    }

    private func assertProcessExited(_ pid: pid_t) async throws {
        for _ in 0..<100 {
            if Darwin.kill(pid, 0) == -1, errno == ESRCH { return }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTFail("Child process \(pid) is still running")
    }

    private enum TestFailure: Error {
        case pidMissing
        case invalidPID
    }
}
