import SwiftUI

struct ResearchReportPageTurnHint: Equatable {
    let direction: Int
    let distance: CGFloat
    let threshold: CGFloat

    var progress: CGFloat { min(1, distance / threshold) }
    var isArmed: Bool { distance >= threshold }
}

struct ResearchReportPageTurnGesture {
    static let threshold: CGFloat = 72
    private(set) var direction = 0
    private(set) var maximumDistance: CGFloat = 0

    mutating func update(direction: Int, overscroll: CGFloat) {
        guard direction != 0 else {
            reset()
            return
        }
        if self.direction != 0, self.direction != direction { reset() }
        self.direction = direction
        maximumDistance = max(maximumDistance, overscroll)
    }

    mutating func finish(canTurn: Bool) -> Int? {
        defer { reset() }
        guard canTurn, maximumDistance >= Self.threshold else { return nil }
        return direction
    }

    mutating func reset() {
        direction = 0
        maximumDistance = 0
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
    var canPageBoundary: ((Int) -> Bool)?
    @Published private(set) var pageTurnHint: ResearchReportPageTurnHint?
    private var wheelMonitor: Any?
    private var pageTurnGesture = ResearchReportPageTurnGesture()
    private var lastPageTurn = Date.distantPast
    private var originalVerticalElasticity: NSScrollView.Elasticity?

    deinit {
        if let wheelMonitor {
            NSEvent.removeMonitor(wheelMonitor)
        }
    }

    func attach(
        scrollView: NSScrollView,
        pageBoundary: @escaping (Int) -> Void,
        canPageBoundary: @escaping (Int) -> Bool
    ) {
        if self.scrollView !== scrollView { detach() }
        self.scrollView = scrollView
        self.pageBoundary = pageBoundary
        self.canPageBoundary = canPageBoundary
        if originalVerticalElasticity == nil {
            originalVerticalElasticity = scrollView.verticalScrollElasticity
            scrollView.verticalScrollElasticity = .allowed
        }
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
        if let scrollView, let originalVerticalElasticity {
            scrollView.verticalScrollElasticity = originalVerticalElasticity
        }
        scrollView = nil
        pageBoundary = nil
        canPageBoundary = nil
        originalVerticalElasticity = nil
        pageTurnGesture.reset()
        pageTurnHint = nil
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
        let direction = event.scrollingDeltaY == 0
            ? 0 : (event.scrollingDeltaY < 0 ? 1 : -1)
        let phase = event.phase
        let isDirectGesture = event.hasPreciseScrollingDeltas
            && event.momentumPhase.isEmpty
            && !phase.isEmpty
        guard isDirectGesture else {
            resetPageTurnGesture()
            return
        }
        if phase.contains(.began) { resetPageTurnGesture() }
        let isFinishing = phase.contains(.ended) || phase.contains(.cancelled)

        // The local monitor runs before AppKit applies the scroll event. Sample
        // on the next main-loop turn so bounds.origin contains real rubber-band
        // displacement instead of inferred wheel distance.
        DispatchQueue.main.async { [weak self, weak scrollView] in
            guard let self, let scrollView,
                  self.scrollView === scrollView else { return }
            self.sampleOverscroll(
                in: scrollView,
                direction: direction,
                isFinishing: isFinishing,
                wasCancelled: phase.contains(.cancelled)
            )
        }
    }

    private func sampleOverscroll(
        in scrollView: NSScrollView,
        direction: Int,
        isFinishing: Bool,
        wasCancelled: Bool
    ) {
        let resolvedDirection = direction == 0
            ? pageTurnGesture.direction : direction
        let documentHeight = scrollView.documentView?.bounds.height ?? 0
        let viewportHeight = scrollView.contentView.bounds.height
        let maximum = max(0, documentHeight - viewportHeight)
        let origin = scrollView.contentView.bounds.origin.y
        let distance = resolvedDirection > 0
            ? max(0, origin - maximum)
            : max(0, -origin)
        let canTurn = resolvedDirection != 0
            && canPageBoundary?(resolvedDirection) == true

        if distance > 0, canTurn {
            pageTurnGesture.update(
                direction: resolvedDirection,
                overscroll: distance
            )
            pageTurnHint = ResearchReportPageTurnHint(
                direction: resolvedDirection,
                distance: max(distance, pageTurnGesture.maximumDistance),
                threshold: ResearchReportPageTurnGesture.threshold
            )
        } else if !isFinishing {
            resetPageTurnGesture()
        }

        guard isFinishing else { return }
        if wasCancelled {
            resetPageTurnGesture()
            return
        }
        let pageDirection = pageTurnGesture.finish(canTurn: canTurn)
        pageTurnHint = nil
        guard let pageDirection,
              Date().timeIntervalSince(lastPageTurn) >= 0.45 else { return }
        lastPageTurn = Date()
        pageBoundary?(pageDirection)
    }

    private func resetPageTurnGesture() {
        pageTurnGesture.reset()
        pageTurnHint = nil
    }
}

struct ResearchReportScrollViewResolver: NSViewRepresentable {
    let coordinator: ResearchReportScrollAnchorCoordinator
    let pageBoundary: (Int) -> Void
    let canPageBoundary: (Int) -> Bool

    func makeNSView(context _: Context) -> ResolverView {
        ResolverView(
            coordinator: coordinator,
            pageBoundary: pageBoundary,
            canPageBoundary: canPageBoundary
        )
    }

    func updateNSView(_ view: ResolverView, context _: Context) {
        view.pageBoundary = pageBoundary
        view.canPageBoundary = canPageBoundary
        view.resolveScrollView()
    }

    final class ResolverView: NSView {
        weak var coordinator: ResearchReportScrollAnchorCoordinator?
        var pageBoundary: (Int) -> Void
        var canPageBoundary: (Int) -> Bool

        init(
            coordinator: ResearchReportScrollAnchorCoordinator,
            pageBoundary: @escaping (Int) -> Void,
            canPageBoundary: @escaping (Int) -> Bool
        ) {
            self.coordinator = coordinator
            self.pageBoundary = pageBoundary
            self.canPageBoundary = canPageBoundary
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
                        pageBoundary: pageBoundary,
                        canPageBoundary: canPageBoundary
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
    @Published private(set) var pageTurnHint: ResearchReportPageTurnHint?
    func captureLayout() -> LayoutSnapshot? { nil }
    func restoreLayout(_: LayoutSnapshot?) async {}
    func scrollToDocumentBottom() async {}
    func isAtDocumentBottom(tolerance _: CGFloat = 2) -> Bool { true }
}

struct ResearchReportScrollViewResolver: View {
    let coordinator: ResearchReportScrollAnchorCoordinator
    let pageBoundary: (Int) -> Void
    let canPageBoundary: (Int) -> Bool
    var body: some View { Color.clear }
}
#endif
