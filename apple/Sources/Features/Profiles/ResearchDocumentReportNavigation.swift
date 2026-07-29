import SwiftUI

extension ResearchDocumentReportView {
    func reloadReport() async {
        loadToken &+= 1
        let token = loadToken
        let focus = selectedComponentID.isEmpty
            ? initialComponentID : selectedComponentID
        do {
            let payload = try await ResearchReportTreeSource.load(
                localRef: artifact.localRef,
                focusedComponentID: focus,
                windowRadius: 2
            )
            try Task.checkCancellation()
            guard token == loadToken else { return }
            let nextHead = ResearchReportHeadFollow.nextChapter(
                previousOutline: document.outlineIDs,
                selectedID: selectedComponentID,
                centeredID: selectedComponentID,
                newOutline: payload.outlineIDs
            )
            let result = document.apply(
                payload,
                focusedAt: payload.focusedComponentID
            )
            hasLoadedReport = true
            error = nil
            if let nextHead {
                reveal(nextHead, behavior: .smooth)
                return
            }
            if selectedComponentID.isEmpty,
               let initial = payload.focusedComponentID {
                selectedComponentID = initial
                requestScroll(to: initial, behavior: .instant)
            } else if (result.replaced || result.addedBeforeFocus),
                      let focused = payload.focusedComponentID {
                requestScroll(to: focused, behavior: .instant)
            }
            await prefetchOutside(payload)
        } catch is CancellationError {
            return
        } catch {
            guard token == loadToken else { return }
            hasLoadedReport = true
            self.error = L10n.text("本地研究报告无法读取")
        }
    }

    func selectTimelineItem(
        _ item: ResearchReportNodeTimelineItem,
        behavior: ResearchReportNavigationBehavior
    ) {
        reveal(item.componentID, behavior: behavior)
    }

    func reveal(
        _ componentID: String,
        behavior: ResearchReportNavigationBehavior
    ) {
        guard !componentID.isEmpty else { return }
        pendingComponentID = componentID
        if document.containsChapter(componentID) {
            requestScroll(to: componentID, behavior: behavior)
            return
        }
        loadToken &+= 1
        let token = loadToken
        Task {
            do {
                let payload = try await ResearchReportTreeSource.load(
                    localRef: artifact.localRef,
                    focusedComponentID: componentID,
                    windowRadius: 2
                )
                try Task.checkCancellation()
                guard token == loadToken,
                      pendingComponentID == componentID else { return }
                _ = document.apply(payload, focusedAt: componentID)
                hasLoadedReport = true
                error = nil
                requestScroll(to: componentID, behavior: behavior)
                await prefetchOutside(payload)
            } catch is CancellationError {
                return
            } catch {
                guard token == loadToken else { return }
                pendingComponentID = ""
                self.error = L10n.text("本地研究报告无法读取")
            }
        }
    }

    func selectVisibleChapter(_ componentID: String) {
        guard !componentID.isEmpty else { return }
        if !pendingComponentID.isEmpty {
            guard componentID == pendingComponentID else { return }
            pendingComponentID = ""
        }
        let windowLoaded = document.containsWindow(
            centeredAt: componentID,
            radius: 2
        )
        guard componentID != selectedComponentID || !windowLoaded else {
            return
        }
        selectedComponentID = componentID
        guard !windowLoaded else { return }
        loadToken &+= 1
        let token = loadToken
        Task {
            do {
                let payload = try await ResearchReportTreeSource.load(
                    localRef: artifact.localRef,
                    focusedComponentID: componentID,
                    windowRadius: 2
                )
                try Task.checkCancellation()
                guard token == loadToken,
                      selectedComponentID == componentID else { return }
                let result = document.apply(
                    payload,
                    focusedAt: componentID
                )
                if result.addedBeforeFocus {
                    requestScroll(to: componentID, behavior: .instant)
                }
                await prefetchOutside(payload)
            } catch is CancellationError {
                return
            } catch {
                guard token == loadToken else { return }
                self.error = L10n.text("本地研究报告无法读取")
            }
        }
    }

    func requestScroll(
        to componentID: String,
        behavior: ResearchReportNavigationBehavior
    ) {
        scrollToken &+= 1
        pendingComponentID = componentID
        let token = scrollToken
        scrollRequest = ResearchReportScrollRequest(
            componentID: componentID,
            token: token,
            behavior: behavior
        )
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(500))
            guard scrollRequest?.token == token,
                  pendingComponentID == componentID else { return }
            pendingComponentID = ""
        }
    }

    func prefetchOutside(_ payload: ResearchReportTreePayload) async {
        await ResearchReportTreeSource.prefetch(
            localRef: artifact.localRef,
            componentIDs: ResearchReportChapterWindow.prefetchIDs(
                outlineIDs: payload.outlineIDs,
                loadedIDs: payload.loadedComponentIDs
            )
        )
    }

    var initialComponentID: String? {
        ResearchReportNodeTimelineBuilder.initialComponentID(
            detail: detail, workPackage: workPackage, steps: steps,
            artifact: artifact, items: timelineItems
        )
    }

    var timelineItems: [ResearchReportNodeTimelineItem] {
        ResearchReportNodeTimelineBuilder.items(
            detail: detail, workPackage: workPackage, steps: steps,
            artifact: artifact, reportOutline: document.outline
        )
    }
}
