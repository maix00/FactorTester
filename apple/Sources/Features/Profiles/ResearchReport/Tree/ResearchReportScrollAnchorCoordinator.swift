import SwiftUI

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
        let anchorID: String
        let anchorPosition: CGFloat
        let documentHeight: CGFloat
    }

    weak var scrollView: NSScrollView?
    private var chapterPositions: [String: CGFloat] = [:]

    func updateChapterPositions(_ positions: [String: CGFloat]) {
        chapterPositions = positions
    }

    func captureLayout(anchorID requestedID: String? = nil) -> LayoutSnapshot? {
        guard let scrollView else { return nil }
        let anchorID = requestedID.flatMap { chapterPositions[$0] == nil ? nil : $0 }
            ?? chapterPositions.min(by: {
                abs($0.value - 96) < abs($1.value - 96)
            })?.key
        guard let anchorID,
              let anchorPosition = chapterPositions[anchorID] else { return nil }
        return LayoutSnapshot(
            origin: scrollView.contentView.bounds.origin,
            anchorID: anchorID,
            anchorPosition: anchorPosition,
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
            guard let currentAnchorPosition = chapterPositions[
                snapshot.anchorID
            ] else {
                try? await Task.sleep(for: .milliseconds(16))
                continue
            }
            let layoutDidSettle = abs(
                documentView.bounds.height - snapshot.documentHeight
            ) > 0.5 || abs(
                currentAnchorPosition - snapshot.anchorPosition
            ) > 0.5
            if !layoutDidSettle, attempt < 2 {
                try? await Task.sleep(for: .milliseconds(16))
                continue
            }
            let targetY = ResearchReportScrollAnchorMath.restoredViewportOffset(
                currentOffset: snapshot.origin.y,
                previousAnchorPosition: snapshot.anchorPosition,
                currentAnchorPosition: currentAnchorPosition
            )
            scrollView.contentView.scroll(to: NSPoint(
                x: snapshot.origin.x,
                y: targetY
            ))
            scrollView.reflectScrolledClipView(scrollView.contentView)
            if attempt >= 2 || layoutDidSettle { return }
            try? await Task.sleep(for: .milliseconds(16))
        }
    }

    func restoreReadingOffset(_ chapterOffset: CGFloat) async {
        guard chapterOffset > 0 else { return }
        await Task.yield()
        guard !Task.isCancelled, let scrollView else { return }
        let origin = scrollView.contentView.bounds.origin
        scrollView.contentView.scroll(to: NSPoint(
            x: origin.x,
            y: ResearchReportScrollAnchorMath.restoredReadingOffset(
                currentOffset: origin.y,
                chapterOffset: chapterOffset
            )
        ))
        scrollView.reflectScrolledClipView(scrollView.contentView)
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
}

struct ResearchReportScrollViewResolver: NSViewRepresentable {
    let coordinator: ResearchReportScrollAnchorCoordinator

    func makeNSView(context _: Context) -> ResolverView {
        ResolverView(coordinator: coordinator)
    }

    func updateNSView(_ view: ResolverView, context _: Context) {
        view.resolveScrollView()
    }

    final class ResolverView: NSView {
        weak var coordinator: ResearchReportScrollAnchorCoordinator?

        init(coordinator: ResearchReportScrollAnchorCoordinator) {
            self.coordinator = coordinator
            super.init(frame: .zero)
        }

        @available(*, unavailable)
        required init?(coder _: NSCoder) { nil }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            resolveScrollView()
        }

        func resolveScrollView() {
            var ancestor = superview
            while let view = ancestor {
                if let scrollView = view as? NSScrollView {
                    coordinator?.scrollView = scrollView
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
    func updateChapterPositions(_: [String: CGFloat]) {}
    func captureLayout(anchorID _: String? = nil) -> LayoutSnapshot? { nil }
    func restoreLayout(_: LayoutSnapshot?) async {}
    func restoreReadingOffset(_: CGFloat) async {}
    func scrollToDocumentBottom() async {}
    func isAtDocumentBottom(tolerance _: CGFloat = 2) -> Bool { true }
}

struct ResearchReportScrollViewResolver: View {
    let coordinator: ResearchReportScrollAnchorCoordinator
    var body: some View { Color.clear }
}
#endif
