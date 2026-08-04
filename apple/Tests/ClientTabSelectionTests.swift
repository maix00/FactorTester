import XCTest
@testable import FTClient

final class ClientTabSelectionTests: XCTestCase {
    func testEveryPinnedSelectionMountsDestinationBeforeSelectingIt() {
        let destinations = [
            ClientTab.research, .jobs, .factorLibrary, .products, .profiles,
            .accountSettings,
        ]

        for destination in destinations {
            var tabs = [ClientTab.home]
            var selection = ClientTab.home.id
            var mountedWhenSelected = false
            let router = ClientTabSelectionRouter(
                tabs: { tabs },
                setTabs: { tabs = $0 },
                setSelection: { selectedID in
                    mountedWhenSelected = tabs.contains {
                        $0.id == selectedID
                    }
                    selection = selectedID
                }
            )

            router.select(destination.id)

            XCTAssertTrue(
                tabs.contains { $0.id == destination.id },
                destination.id
            )
            XCTAssertEqual(selection, destination.id)
            XCTAssertTrue(mountedWhenSelected, destination.id)
        }
    }

    func testUnknownSelectionDoesNotInventATab() {
        var tabs = [ClientTab.home]
        var selection = ClientTab.home.id
        let router = ClientTabSelectionRouter(
            tabs: { tabs },
            setTabs: { tabs = $0 },
            setSelection: { selection = $0 }
        )

        router.select("work-package:not-mounted")

        XCTAssertEqual(tabs.map(\.id), [ClientTab.home.id])
        XCTAssertEqual(selection, "work-package:not-mounted")
    }

    func testEachTestLauncherCreatesANewClosablePage() {
        for launcher in [ClientTab.icTestLauncher, .backtestLauncher] {
            var tabs = [ClientTab.home]
            var selection = ClientTab.home.id
            let router = ClientTabSelectionRouter(
                tabs: { tabs },
                setTabs: { tabs = $0 },
                setSelection: { selection = $0 }
            )

            router.select(launcher.id)
            let first = selection
            router.select(launcher.id)

            XCTAssertNotEqual(first, selection)
            XCTAssertEqual(tabs.count, 3)
            XCTAssertTrue(tabs.dropFirst().allSatisfy(\.isClosable))
            XCTAssertFalse(tabs.contains { $0.id == launcher.id })
        }
    }
}
