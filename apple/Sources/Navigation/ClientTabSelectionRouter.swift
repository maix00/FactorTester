import Foundation

/// Keeps SwiftUI's sidebar selection and the selected detail tab atomic.
///
/// `List(selection:)` may update its binding without running a row's gesture.
/// A pinned destination must therefore be mounted before its ID becomes the
/// active selection, otherwise the detail view cannot resolve the destination.
struct ClientTabSelectionRouter {
    let tabs: () -> [ClientTab]
    let setTabs: ([ClientTab]) -> Void
    let setSelection: (String) -> Void
    let launcher: (String) -> ClientTab?

    init(
        tabs: @escaping () -> [ClientTab],
        setTabs: @escaping ([ClientTab]) -> Void,
        setSelection: @escaping (String) -> Void,
        launcher: @escaping (String) -> ClientTab? = {
            ClientTab.pinnedLauncher(id: $0)
        }
    ) {
        self.tabs = tabs
        self.setTabs = setTabs
        self.setSelection = setSelection
        self.launcher = launcher
    }

    func select(_ id: String) {
        var mounted = tabs()
        if let destination = ClientTab.testDestination(forLauncherID: id) {
            mounted.append(destination)
            setTabs(mounted)
            setSelection(destination.id)
            return
        }
        if let destination = launcher(id),
           !mounted.contains(where: { $0.id == destination.id }) {
            mounted.append(destination)
            setTabs(mounted)
            setSelection(destination.id)
            return
        }
        setSelection(id)
    }
}

extension ClientTab {
    static func testDestination(forLauncherID id: String) -> ClientTab? {
        switch id {
        case icTestLauncher.id: return .icTest()
        case backtestLauncher.id: return .backtest()
        default: return nil
        }
    }

    static func pinnedLauncher(id: String) -> ClientTab? {
        switch id {
        case home.id: return .home
        case research.id: return .research
        case jobs.id: return .jobs
        case factorLibrary.id: return .factorLibrary
        case products.id: return .products
        case profiles.id: return .profiles
        case accountSettings.id: return .accountSettings
        default: return nil
        }
    }
}
