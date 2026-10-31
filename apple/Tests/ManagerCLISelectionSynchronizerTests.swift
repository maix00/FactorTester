#if os(macOS)
import Foundation
import XCTest
@testable import FTClient

@MainActor
final class ManagerCLISelectionSynchronizerTests: XCTestCase {
    func testRapidSwitchesFinishWithLatestManager() async throws {
        let first = try XCTUnwrap(URL(string: "https://first.example:7998"))
        let second = try XCTUnwrap(URL(string: "https://second.example:7998"))
        var selected: URL? = first
        var calls: [URL] = []
        var resumeFirst: CheckedContinuation<Void, Never>?
        let started = expectation(description: "first update started")
        let finished = expectation(description: "second update finished")
        let synchronizer = ManagerCLISelectionSynchronizer(current: { selected }, runner: { value in
            calls.append(value)
            if value == first {
                await withCheckedContinuation { continuation in
                    resumeFirst = continuation
                    started.fulfill()
                }
            } else { finished.fulfill() }
        })
        synchronizer.schedule(first)
        await fulfillment(of: [started], timeout: 2)
        selected = second
        synchronizer.schedule(second)
        resumeFirst?.resume()
        await fulfillment(of: [finished], timeout: 2)
        XCTAssertEqual(calls, [first, second])
    }
}
#endif
