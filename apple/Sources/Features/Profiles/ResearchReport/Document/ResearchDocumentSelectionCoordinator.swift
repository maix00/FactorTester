#if os(macOS)
import AppKit

@MainActor
final class ResearchDocumentSelectionCoordinator: ObservableObject {
    private struct Entry {
        weak var view: ResearchInlineTextView?
        let order: Int
    }

    @Published private(set) var hasSelection = false
    private var entries: [Entry] = []
    private var nextOrder = 0
    private weak var anchorView: ResearchInlineTextView?
    private var anchorIndex = 0
    private var eventMonitor: Any?

    var hasCrossViewSelection: Bool {
        selectedViews.count > 1
    }

    var selectedPlainText: String {
        orderedViews.compactMap { view in
            let range = view.selectedRange()
            guard range.length > 0 else { return nil }
            return (view.string as NSString).substring(with: range)
        }
        .joined(separator: "\n")
    }

    func register(_ view: ResearchInlineTextView) {
        compactEntries()
        guard !entries.contains(where: { $0.view === view }) else { return }
        entries.append(Entry(view: view, order: nextOrder))
        nextOrder += 1
        view.selectionCoordinator = self
    }

    func unregister(_ view: ResearchInlineTextView) {
        entries.removeAll { $0.view == nil || $0.view === view }
        if anchorView === view {
            anchorView = nil
            updateSelectionState()
        }
        if view.selectionCoordinator === self {
            view.selectionCoordinator = nil
        }
    }

    func start() {
        guard eventMonitor == nil else { return }
        eventMonitor = NSEvent.addLocalMonitorForEvents(
            matching: .leftMouseDown
        ) { [weak self] event in
            guard let self else { return event }
            MainActor.assumeIsolated {
                if !self.containsRegisteredView(at: event) {
                    self.clearSelection()
                }
            }
            return event
        }
    }

    func stop() {
        if let eventMonitor {
            NSEvent.removeMonitor(eventMonitor)
            self.eventMonitor = nil
        }
        clearSelection()
    }

    func beginSelection(
        in view: ResearchInlineTextView,
        characterIndex: Int
    ) {
        clearRanges()
        anchorView = view
        anchorIndex = clamped(characterIndex, in: view)
        view.setSelectedRange(NSRange(location: anchorIndex, length: 0))
        updateSelectionState()
    }

    func extendSelection(
        to view: ResearchInlineTextView,
        characterIndex: Int
    ) {
        guard let anchorView else { return }
        let views = orderedViews
        guard let anchorPosition = views.firstIndex(where: { $0 === anchorView }),
              let targetPosition = views.firstIndex(where: { $0 === view }) else {
            return
        }
        let targetIndex = clamped(characterIndex, in: view)
        clearRanges()

        if anchorPosition == targetPosition {
            let lower = min(anchorIndex, targetIndex)
            anchorView.setSelectedRange(NSRange(
                location: lower,
                length: abs(targetIndex - anchorIndex)
            ))
        } else if anchorPosition < targetPosition {
            selectForward(
                views: views,
                anchorPosition: anchorPosition,
                targetPosition: targetPosition,
                targetIndex: targetIndex
            )
        } else {
            selectBackward(
                views: views,
                anchorPosition: anchorPosition,
                targetPosition: targetPosition,
                targetIndex: targetIndex
            )
        }
        updateSelectionState()
    }

    func clearSelection() {
        anchorView = nil
        clearRanges()
        updateSelectionState()
    }

    func textView(at event: NSEvent) -> ResearchInlineTextView? {
        guard let window = event.window else { return nil }
        return orderedViews.first { view in
            view.window === window
                && view.bounds.contains(view.convert(event.locationInWindow, from: nil))
        }
    }

    private var selectedViews: [ResearchInlineTextView] {
        orderedViews.filter { $0.selectedRange().length > 0 }
    }

    private var orderedViews: [ResearchInlineTextView] {
        compactEntries()
        let liveEntries = entries.compactMap { entry in
            entry.view.map { (view: $0, order: entry.order) }
        }
        guard liveEntries.allSatisfy({ $0.view.window != nil }) else {
            return liveEntries.sorted { $0.order < $1.order }.map(\.view)
        }
        return liveEntries.sorted { left, right in
            let leftRect = left.view.convert(left.view.bounds, to: nil)
            let rightRect = right.view.convert(right.view.bounds, to: nil)
            if abs(leftRect.maxY - rightRect.maxY) > 1 {
                return leftRect.maxY > rightRect.maxY
            }
            if abs(leftRect.minX - rightRect.minX) > 1 {
                return leftRect.minX < rightRect.minX
            }
            return left.order < right.order
        }
        .map(\.view)
    }

    private func selectForward(
        views: [ResearchInlineTextView],
        anchorPosition: Int,
        targetPosition: Int,
        targetIndex: Int
    ) {
        for position in anchorPosition...targetPosition {
            let current = views[position]
            if position == anchorPosition {
                current.setSelectedRange(NSRange(
                    location: anchorIndex,
                    length: current.string.utf16.count - anchorIndex
                ))
            } else if position == targetPosition {
                current.setSelectedRange(NSRange(
                    location: 0,
                    length: targetIndex
                ))
            } else {
                selectAll(in: current)
            }
        }
    }

    private func selectBackward(
        views: [ResearchInlineTextView],
        anchorPosition: Int,
        targetPosition: Int,
        targetIndex: Int
    ) {
        for position in targetPosition...anchorPosition {
            let current = views[position]
            if position == targetPosition {
                current.setSelectedRange(NSRange(
                    location: targetIndex,
                    length: current.string.utf16.count - targetIndex
                ))
            } else if position == anchorPosition {
                current.setSelectedRange(NSRange(
                    location: 0,
                    length: anchorIndex
                ))
            } else {
                selectAll(in: current)
            }
        }
    }

    private func selectAll(in view: ResearchInlineTextView) {
        view.setSelectedRange(NSRange(
            location: 0,
            length: view.string.utf16.count
        ))
    }

    private func clearRanges() {
        orderedViews.forEach {
            $0.setSelectedRange(NSRange(location: 0, length: 0))
        }
    }

    private func updateSelectionState() {
        hasSelection = orderedViews.contains {
            $0.selectedRange().length > 0
        }
    }

    private func containsRegisteredView(at event: NSEvent) -> Bool {
        textView(at: event) != nil
    }

    private func compactEntries() {
        entries.removeAll { $0.view == nil }
    }

    private func clamped(
        _ index: Int,
        in view: ResearchInlineTextView
    ) -> Int {
        min(max(index, 0), view.string.utf16.count)
    }
}
#endif
