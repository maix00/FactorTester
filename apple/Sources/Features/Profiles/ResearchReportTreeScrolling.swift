import SwiftUI

extension ResearchReportTreePage {
    @MainActor
    func scrollIfNeeded(_ proxy: ScrollViewProxy) async {
        guard let request = scrollRequest,
              lastScrollToken != request.token,
              rootComponentsByID[request.componentID] != nil
        else { return }

        await Task.yield()
        guard !Task.isCancelled,
              lastScrollToken != request.token else { return }
        performScroll(request, proxy: proxy)

        let initialDelay = request.behavior == .smooth ? 260 : 80
        var stableObservations = 0
        for attempt in 0..<8 {
            try? await Task.sleep(
                for: .milliseconds(initialDelay + (attempt * 55))
            )
            guard !Task.isCancelled,
                  scrollRequest?.token == request.token else { return }
            let completed = ResearchReportChapterViewport.completedScroll(
                to: request.componentID,
                positions: chapterPositions,
                loadedIDs: rootComponentIDs,
                canClampAtDocumentBottom: documentTailIsFullyVisible,
                viewportHeight: viewportHeight
            )
            stableObservations = completed ? stableObservations + 1 : 0
            if stableObservations >= 2 {
                lastScrollToken = request.token
                flash(request.componentID)
                visibleChapter(request.componentID)
                return
            }
            proxy.scrollTo(request.componentID, anchor: .top)
        }
    }

    func performScroll(
        _ request: ResearchReportScrollRequest,
        proxy: ScrollViewProxy
    ) {
        if request.behavior == .smooth {
            withAnimation(.easeInOut(duration: 0.22)) {
                proxy.scrollTo(request.componentID, anchor: .top)
            }
        } else {
            proxy.scrollTo(request.componentID, anchor: .top)
        }
    }

    func updateVisibleChapter(_ positions: [String: CGFloat]) {
        if let request = scrollRequest,
           lastScrollToken != request.token {
            return
        }
        let anchored = ResearchReportChapterViewport.activeID(
            positions: positions,
            orderedIDs: chapterOrder
        )
        guard let active = retainedTailTarget ?? anchored else { return }
        visibleChapter(active)
    }

    var chapterPositions: [String: CGFloat] {
        chapterGeometry.mapValues(\.minY)
    }

    func chapterPositionsChanged(
        from previous: [String: ResearchReportChapterGeometry],
        to current: [String: ResearchReportChapterGeometry]
    ) -> Bool {
        guard Set(previous.keys) == Set(current.keys) else { return true }
        return current.contains { id, geometry in
            guard let old = previous[id] else { return true }
            return abs(old.minY - geometry.minY) > 1
        }
    }

    var documentTailIsFullyVisible: Bool {
        guard viewportHeight > 0,
              let tail = chapterOrder.last,
              rootComponentsByID[tail] != nil,
              let geometry = chapterGeometry[tail] else {
            return false
        }
        return geometry.minY >= 0
            && geometry.minY + geometry.height <= viewportHeight + 1
    }

    var retainedTailTarget: String? {
        guard let request = scrollRequest,
              request.token == lastScrollToken,
              request.componentID == chapterOrder.last,
              viewportHeight > 0,
              let geometry = chapterGeometry[request.componentID],
              geometry.minY >= 0,
              geometry.minY < viewportHeight else {
            return nil
        }
        return request.componentID
    }

    func flash(_ componentID: String) {
        highlightTask?.cancel()
        highlightedComponentID = componentID
        highlightTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(1_400))
            guard !Task.isCancelled else { return }
            withAnimation(.easeOut(duration: 0.25)) {
                highlightedComponentID = ""
            }
        }
    }
}
