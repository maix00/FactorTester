import SwiftUI

struct ResearchReportPageTurnThreshold {
    private(set) var distance: CGFloat = 0
    private var direction = 0

    mutating func consume(
        deltaY: CGFloat,
        precise: Bool,
        atBoundary: Bool
    ) -> Int? {
        let nextDirection = deltaY < 0 ? 1 : -1
        guard atBoundary else {
            reset()
            return nil
        }
        if direction != 0, direction != nextDirection { reset() }
        direction = nextDirection
        distance += abs(deltaY) * (precise ? 1 : 18)
        guard distance >= 72 else { return nil }
        reset()
        return nextDirection
    }

    mutating func reset() {
        distance = 0
        direction = 0
    }
}

private struct ResearchReportScrollAnchorCoordinatorKey: EnvironmentKey {
    static let defaultValue: ResearchReportScrollAnchorCoordinator? = nil
}

extension EnvironmentValues {
    var researchReportScrollAnchorCoordinator:
        ResearchReportScrollAnchorCoordinator? {
        get { self[ResearchReportScrollAnchorCoordinatorKey.self] }
        set { self[ResearchReportScrollAnchorCoordinatorKey.self] = newValue }
    }
}

#if os(macOS)
import AppKit

@MainActor
final class ResearchReportScrollAnchorCoordinator: ObservableObject {
    struct LayoutSnapshot {
        let origin: NSPoint
        let documentHeight: CGFloat
    }

    weak var scrollView: NSScrollView?
    var pageBoundary: ((Int) -> Void)?
    private var wheelMonitor: Any?
    private var pageTurnThreshold = ResearchReportPageTurnThreshold()
    private var lastPageTurn = Date.distantPast

    deinit {
        if let wheelMonitor {
            NSEvent.removeMonitor(wheelMonitor)
        }
    }

    func attach(
        scrollView: NSScrollView,
        pageBoundary: @escaping (Int) -> Void
    ) {
        self.scrollView = scrollView
        self.pageBoundary = pageBoundary
        guard wheelMonitor == nil else { return }
        wheelMonitor = NSEvent.addLocalMonitorForEvents(
            matching: .scrollWheel
        ) { [weak self] event in
            self?.handleWheel(event)
            return event
        }
    }

    func detach() {
        if let wheelMonitor {
            NSEvent.removeMonitor(wheelMonitor)
        }
        wheelMonitor = nil
        scrollView = nil
        pageBoundary = nil
        pageTurnThreshold.reset()
    }

    func captureLayout() -> LayoutSnapshot? {
        guard let scrollView else { return nil }
        return LayoutSnapshot(
            origin: scrollView.contentView.bounds.origin,
            documentHeight: scrollView.documentView?.bounds.height ?? 0
        )
    }

    func restoreLayout(_ snapshot: LayoutSnapshot?) async {
        guard let snapshot else { return }
        for attempt in 0..<5 {
            await Task.yield()
            guard !Task.isCancelled,
                  let scrollView,
                  let documentView = scrollView.documentView else { return }
            scrollView.layoutSubtreeIfNeeded()
            documentView.layoutSubtreeIfNeeded()
            let layoutDidSettle = abs(
                documentView.bounds.height - snapshot.documentHeight
            ) > 0.5
            if !layoutDidSettle, attempt < 2 {
                try? await Task.sleep(for: .milliseconds(16))
                continue
            }
            let maximum = max(
                0,
                documentView.bounds.height
                    - scrollView.contentView.bounds.height
            )
            let targetY = min(maximum, max(0, snapshot.origin.y))
            scrollView.contentView.scroll(to: NSPoint(
                x: snapshot.origin.x,
                y: targetY
            ))
            scrollView.reflectScrolledClipView(scrollView.contentView)
            if attempt >= 2 || layoutDidSettle { return }
            try? await Task.sleep(for: .milliseconds(16))
        }
    }

    func scrollToDocumentBottom() async {
        for attempt in 0..<4 {
            await Task.yield()
            guard !Task.isCancelled,
                  let scrollView,
                  let documentView = scrollView.documentView else { return }
            scrollView.layoutSubtreeIfNeeded()
            documentView.layoutSubtreeIfNeeded()
            let maximum = max(
                0,
                documentView.bounds.height
                    - scrollView.contentView.bounds.height
            )
            scrollView.contentView.scroll(to: NSPoint(
                x: scrollView.contentView.bounds.origin.x,
                y: maximum
            ))
            scrollView.reflectScrolledClipView(scrollView.contentView)
            if attempt >= 1 { return }
            try? await Task.sleep(for: .milliseconds(16))
        }
    }

    func isAtDocumentBottom(tolerance: CGFloat = 2) -> Bool {
        guard let scrollView,
              let documentView = scrollView.documentView else { return false }
        let maximum = max(
            0,
            documentView.bounds.height - scrollView.contentView.bounds.height
        )
        return abs(scrollView.contentView.bounds.origin.y - maximum) <= tolerance
    }

    private func handleWheel(_ event: NSEvent) {
        guard let scrollView,
              event.window === scrollView.window else { return }
        let point = scrollView.convert(event.locationInWindow, from: nil)
        guard scrollView.bounds.contains(point),
              abs(event.scrollingDeltaY) >= abs(event.scrollingDeltaX)
        else { return }
        let maximum = max(
            0,
            (scrollView.documentView?.bounds.height ?? 0)
                - scrollView.contentView.bounds.height
        )
        let origin = scrollView.contentView.bounds.origin.y
        let direction = event.scrollingDeltaY < 0 ? 1 : -1
        let atBoundary = direction > 0
            ? origin >= maximum - 1
            : origin <= 1
        if event.phase == .began || event.momentumPhase == .began {
            pageTurnThreshold.reset()
        }
        guard let pageDirection = pageTurnThreshold.consume(
            deltaY: event.scrollingDeltaY,
            precise: event.hasPreciseScrollingDeltas,
            atBoundary: atBoundary
        ),
              Date().timeIntervalSince(lastPageTurn) >= 0.45 else { return }
        lastPageTurn = Date()
        pageBoundary?(pageDirection)
    }
}

struct ResearchReportScrollViewResolver: NSViewRepresentable {
    let coordinator: ResearchReportScrollAnchorCoordinator
    let pageBoundary: (Int) -> Void

    func makeNSView(context _: Context) -> ResolverView {
        ResolverView(
            coordinator: coordinator,
            pageBoundary: pageBoundary
        )
    }

    func updateNSView(_ view: ResolverView, context _: Context) {
        view.resolveScrollView()
    }

    final class ResolverView: NSView {
        weak var coordinator: ResearchReportScrollAnchorCoordinator?
        let pageBoundary: (Int) -> Void

        init(
            coordinator: ResearchReportScrollAnchorCoordinator,
            pageBoundary: @escaping (Int) -> Void
        ) {
            self.coordinator = coordinator
            self.pageBoundary = pageBoundary
            super.init(frame: .zero)
        }

        @available(*, unavailable)
        required init?(coder _: NSCoder) { nil }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if window == nil {
                coordinator?.detach()
                return
            }
            resolveScrollView()
        }

        func resolveScrollView() {
            var ancestor = superview
            while let view = ancestor {
                if let scrollView = view as? NSScrollView {
                    coordinator?.attach(
                        scrollView: scrollView,
                        pageBoundary: pageBoundary
                    )
                    return
                }
                ancestor = view.superview
            }
        }
    }
}
#else
@MainActor
final class ResearchReportScrollAnchorCoordinator: ObservableObject {
    struct LayoutSnapshot {}
    func captureLayout() -> LayoutSnapshot? { nil }
    func restoreLayout(_: LayoutSnapshot?) async {}
    func scrollToDocumentBottom() async {}
    func isAtDocumentBottom(tolerance _: CGFloat = 2) -> Bool { true }
}

struct ResearchReportScrollViewResolver: View {
    let coordinator: ResearchReportScrollAnchorCoordinator
    let pageBoundary: (Int) -> Void
    var body: some View { Color.clear }
}
#endif
