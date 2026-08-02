import SwiftUI

extension ResearchDocumentReportView {
    func reloadReport() async {
        chapterLoadTask?.cancel()
        chapterLoadTask = nil
        loadToken &+= 1
        let token = loadToken
        let wasLoaded = hasLoadedReport
        let authoritativeChapterID = activeGraphChapterID
        let focus = wasLoaded
            ? ResearchReportNavigationFocus.preferred(
                pendingID: pendingComponentID,
                selectedID: selectedComponentID,
                initialID: authoritativeChapterID ?? initialComponentID
            )
            : (pendingComponentID.isEmpty ? nil : pendingComponentID)
        do {
            let payload = try await ResearchReportTreeSource.load(
                localRef: artifact.localRef,
                focusedComponentID: focus
            )
            try Task.checkCancellation()
            guard token == loadToken else { return }
            let nextHead = ResearchReportHeadFollow.nextChapter(
                previousOutline: document.outlineIDs,
                selectedID: selectedComponentID,
                centeredID: selectedComponentID,
                newOutline: payload.outlineIDs
            )
            _ = document.apply(
                payload,
                focusedAt: payload.focusedComponentID
            )
            tabSession.generation = payload.generation
            hasLoadedReport = true
            error = nil
            if let initial = ResearchReportInitialNavigation.destination(
                wasLoaded: wasLoaded,
                hasExplicitTarget: !pendingComponentID.isEmpty,
                outlineIDs: payload.outlineIDs
            ) {
                appliedGraphNavigationID = graphNavigationID
                tabSession.appliedGraphNavigationID = graphNavigationID
                selectedComponentID = initial.componentID
                tabSession.selectedChapterID = initial.componentID
                if document.containsChapter(initial.componentID) {
                    requestScroll(
                        to: initial.componentID,
                        behavior: .instant,
                        destination: initial.scrollDestination
                    )
                } else {
                    reveal(
                        initial.componentID,
                        behavior: .instant,
                        destination: initial.scrollDestination
                    )
                    return
                }
                return
            }
            if let active = ResearchReportGraphAdvanceFollow.target(
                appliedNavigationID: appliedGraphNavigationID,
                currentNavigationID: graphNavigationID,
                authoritativeChapterID: authoritativeChapterID,
                outline: payload.outlineIDs
            ) {
                appliedGraphNavigationID = graphNavigationID
                tabSession.appliedGraphNavigationID = graphNavigationID
                reveal(active, behavior: wasLoaded ? .smooth : .instant)
                return
            }
            if let nextHead {
                reveal(nextHead, behavior: .smooth)
                return
            }
            if !wasLoaded,
               let rememberedChapterID = rememberedChapterID(
                    in: payload.outlineIDs
               ) {
                selectedComponentID = rememberedChapterID
                tabSession.selectedChapterID = rememberedChapterID
                requestScroll(
                    to: rememberedChapterID,
                    behavior: .instant
                )
                return
            }
            if selectedComponentID.isEmpty,
               let initial = initialComponentID
                    ?? payload.focusedComponentID {
                if document.containsChapter(initial) {
                    requestScroll(to: initial, behavior: .instant)
                } else {
                    reveal(initial, behavior: .instant)
                    return
                }
            } else if !payload.outlineIDs.contains(selectedComponentID),
                      let focused = payload.focusedComponentID {
                selectedComponentID = ""
                requestScroll(to: focused, behavior: .instant)
            }
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
        behavior: ResearchReportNavigationBehavior,
        destination: ResearchReportScrollDestination = .chapterTop
    ) {
        guard !componentID.isEmpty else { return }
        pendingComponentID = componentID
        if document.containsChapter(componentID) {
            selectedComponentID = componentID
            tabSession.selectedChapterID = componentID
            pendingComponentID = ""
            requestScroll(
                to: componentID,
                behavior: behavior,
                destination: destination
            )
            return
        }
        loadToken &+= 1
        let token = loadToken
        chapterLoadTask?.cancel()
        chapterLoadTask = Task {
            do {
                let payload = try await ResearchReportTreeSource.load(
                    localRef: artifact.localRef,
                    focusedComponentID: componentID
                )
                try Task.checkCancellation()
                guard token == loadToken,
                      pendingComponentID == componentID else { return }
                _ = document.apply(payload, focusedAt: componentID)
                hasLoadedReport = true
                error = nil
                guard let resolved = payload.outlineIDs.contains(componentID)
                    ? componentID : payload.focusedComponentID else {
                    pendingComponentID = ""
                    self.error = L10n.text("本地研究报告无法读取")
                    return
                }
                selectedComponentID = resolved
                tabSession.selectedChapterID = resolved
                pendingComponentID = ""
                requestScroll(
                    to: resolved,
                    behavior: behavior,
                    destination: destination
                )
            } catch is CancellationError {
                return
            } catch {
                guard token == loadToken else { return }
                pendingComponentID = ""
                self.error = L10n.text("本地研究报告无法读取")
            }
        }
    }

    func selectAdjacentChapter(_ direction: Int) {
        guard direction != 0,
              let current = document.outlineIDs.firstIndex(
                of: selectedComponentID
              ) else { return }
        let next = current + (direction > 0 ? 1 : -1)
        guard document.outlineIDs.indices.contains(next) else { return }
        reveal(
            document.outlineIDs[next],
            behavior: .instant,
            destination: .chapterTop
        )
    }

    func requestScroll(
        to componentID: String,
        behavior: ResearchReportNavigationBehavior,
        destination: ResearchReportScrollDestination = .chapterTop
    ) {
        scrollToken &+= 1
        let token = scrollToken
        scrollRequest = ResearchReportScrollRequest(
            componentID: componentID,
            token: token,
            behavior: behavior,
            destination: destination
        )
    }

    func rememberedChapterID(in outlineIDs: [String]) -> String? {
        let candidates = [
            tabSession.selectedChapterID.isEmpty
                ? nil : tabSession.selectedChapterID,
        ]
        return candidates.compactMap { $0 }.first {
            outlineIDs.contains($0)
        }
    }

    var initialComponentID: String? {
        ResearchReportNodeTimelineBuilder.initialComponentID(
            detail: detail, workPackage: workPackage, steps: steps,
            artifact: artifact, items: timelineItems,
            reportOutline: document.outline
        )
    }

    var activeGraphChapterID: String? {
        ResearchReportNodeTimelineBuilder.activeChapterComponentID(
            detail: detail,
            workPackage: workPackage,
            steps: steps,
            artifact: artifact,
            reportOutline: document.outline
        )
    }

    var graphNavigationID: String {
        [
            detail.branchRef,
            detail.latestTraceRef ?? "",
            detail.currentNode,
        ].joined(separator: "|")
    }

    var timelineItems: [ResearchReportNodeTimelineItem] {
        ResearchReportNodeTimelineBuilder.items(
            detail: detail, workPackage: workPackage, steps: steps,
            artifact: artifact, reportOutline: document.outline
        )
    }

}
