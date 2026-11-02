import XCTest
@testable import TradeResearch

final class BundledRuntimeActivatorTests: XCTestCase {
    func testSelectsExecutableAndReceiptFromSameBundleRoot() {
        let root = URL(fileURLWithPath: "/bundle/Contents/Resources", isDirectory: true)
        let old = root.appendingPathComponent("FactorTester/bin/factortester").path
        let current = root.appendingPathComponent("FactorTester/bin/traderesearch").path
        let renamed = root.appendingPathComponent("TradeResearch/bin/traderesearch").path
        let names = ["traderesearch", "factortester"]
        let both = ClientCLIResolution.bundledExecutable(resourceURL: root, names: names) {
            [old, current, renamed].contains($0)
        }
        XCTAssertEqual(both?.executable.path, renamed)
        XCTAssertEqual(both?.resources.path, root.appendingPathComponent("TradeResearch").path)
        let shipped = ClientCLIResolution.bundledExecutable(resourceURL: root, names: names) {
            [old, current].contains($0)
        }
        XCTAssertEqual(shipped?.executable.path, current)
        XCTAssertEqual(shipped?.resources.path, root.appendingPathComponent("FactorTester").path)
        let legacy = ClientCLIResolution.bundledExecutable(resourceURL: root, names: names) { $0 == old }
        XCTAssertEqual(legacy?.executable.path, old)
        XCTAssertNil(ClientCLIResolution.bundledExecutable(resourceURL: root, names: names) { _ in false })
    }

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

        let starts = await probe.starts
        XCTAssertEqual(starts, 1)
    }
}

private actor ActivationProbe {
    private(set) var starts = 0

    func recordStart() {
        starts += 1
    }
}
