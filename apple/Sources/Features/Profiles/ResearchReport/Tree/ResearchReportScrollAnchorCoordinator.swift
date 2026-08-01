import SwiftUI

#if os(macOS)
import AppKit

@MainActor
final class ResearchReportScrollAnchorCoordinator: ObservableObject {
    struct Snapshot {
        let origin: NSPoint
        let documentHeight: CGFloat
    }

    weak var scrollView: NSScrollView?

    func capture() -> Snapshot? {
        guard let scrollView,
              let documentView = scrollView.documentView else { return nil }
        return Snapshot(
            origin: scrollView.contentView.bounds.origin,
            documentHeight: documentView.bounds.height
        )
    }

    func restoreAfterPrepending(_ snapshot: Snapshot?) async {
        guard let snapshot else { return }
        for _ in 0..<4 {
            await Task.yield()
            guard !Task.isCancelled,
                  let scrollView,
                  let documentView = scrollView.documentView else { return }
            scrollView.layoutSubtreeIfNeeded()
            documentView.layoutSubtreeIfNeeded()
            let addedHeight = documentView.bounds.height - snapshot.documentHeight
            guard addedHeight > 0.5 else {
                try? await Task.sleep(for: .milliseconds(16))
                continue
            }
            scrollView.contentView.scroll(to: NSPoint(
                x: snapshot.origin.x,
                y: ResearchReportScrollAnchorMath.restoredOffset(
                    previousOffset: snapshot.origin.y,
                    previousContentHeight: snapshot.documentHeight,
                    newContentHeight: documentView.bounds.height
                )
            ))
            scrollView.reflectScrolledClipView(scrollView.contentView)
            return
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
    struct Snapshot {}
    func capture() -> Snapshot? { nil }
    func restoreAfterPrepending(_: Snapshot?) async {}
    func restoreReadingOffset(_: CGFloat) async {}
}

struct ResearchReportScrollViewResolver: View {
    let coordinator: ResearchReportScrollAnchorCoordinator
    var body: some View { Color.clear }
}
#endif
