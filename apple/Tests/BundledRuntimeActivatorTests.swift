import XCTest
@testable import FTClient

final class BundledRuntimeActivatorTests: XCTestCase {
    func testConcurrentCallersShareOneActivation() async {
        let probe = ActivationProbe()
        let coordinator = BundledRuntimeActivator.makeTestCoordinator {
            await probe.recordStart()
            try? await Task.sleep(nanoseconds: 50_000_000)
        }

        await withTaskGroup(of: Void.self) { group in
            for _ in 0..<2 {
                group.addTask {
                    try? await coordinator.activate()
                }
            }
        }

        XCTAssertEqual(await probe.starts, 1)
    }
}

private actor ActivationProbe {
    private(set) var starts = 0

    func recordStart() {
        starts += 1
    }
}
