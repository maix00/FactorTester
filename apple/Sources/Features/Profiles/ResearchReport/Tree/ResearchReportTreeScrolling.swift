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
        if request.destination == .documentBottom {
            await scrollAnchorCoordinator.scrollToDocumentBottom()
        }
        try? await Task.sleep(for: .milliseconds(80))
        guard !Task.isCancelled,
              scrollRequest?.token == request.token else { return }
        lastScrollToken = request.token
        flash(request.componentID)
    }

    func performScroll(
        _ request: ResearchReportScrollRequest,
        proxy: ScrollViewProxy
    ) {
        let anchor: UnitPoint = request.destination == .documentBottom
            ? .bottom : .top
        if request.behavior == .smooth {
            withAnimation(.easeInOut(duration: 0.22)) {
                proxy.scrollTo(request.componentID, anchor: anchor)
            }
        } else {
            proxy.scrollTo(request.componentID, anchor: anchor)
        }
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
