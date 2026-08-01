import SwiftUI

extension ResearchDocumentReportView {
    func reloadReport() async {
        windowLoadTask?.cancel()
        windowLoadTask = nil
        loadToken &+= 1
        let token = loadToken
        let wasLoaded = hasLoadedReport
        let rememberedGeneration = tabSession.generation
        let authoritativeChapterID = activeGraphChapterID
        let focus = ResearchReportNavigationFocus.preferred(
            pendingID: pendingComponentID,
            selectedID: selectedComponentID,
            initialID: authoritativeChapterID ?? initialComponentID
        )
        do {
            let payload = try await ResearchReportTreeSource.load(
                localRef: artifact.localRef,
                focusedComponentID: focus,
                windowRadius: Self.chapterWindowRadius
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
            let generationMatches = rememberedGeneration == payload.generation
            if !generationMatches, let anchor = tabSession.readingAnchor {
                tabSession.readingAnchor = ResearchReportReadingAnchor(
                    componentID: anchor.componentID,
                    chapterOffset: 0
                )
            }
            tabSession.generation = payload.generation
            hasLoadedReport = true
            error = nil
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
                let chapterOffset = generationMatches
                    && tabSession.readingAnchor?.componentID
                        == rememberedChapterID
                    ? tabSession.readingAnchor?.chapterOffset ?? 0
                    : 0
                requestScroll(
                    to: rememberedChapterID,
                    behavior: .instant,
                    chapterOffset: chapterOffset
                )
                await prefetchOutside(payload)
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
        if document.containsWindow(
            centeredAt: componentID,
            radius: Self.chapterWindowRadius
        ) {
            requestScroll(to: componentID, behavior: behavior)
            return
        }
        loadToken &+= 1
        let token = loadToken
        windowLoadTask?.cancel()
        windowLoadTask = Task {
            do {
                let payload = try await ResearchReportTreeSource.load(
                    localRef: artifact.localRef,
                    focusedComponentID: componentID,
                    windowRadius: Self.chapterWindowRadius
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
                pendingComponentID = resolved
                requestScroll(to: resolved, behavior: behavior)
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
        let windowLoaded = document.containsNavigationBuffer(
            around: componentID
        )
        guard componentID != selectedComponentID || !windowLoaded else {
            return
        }
        selectedComponentID = componentID
        tabSession.selectedChapterID = componentID
        guard !windowLoaded else { return }
        loadToken &+= 1
        let token = loadToken
        windowLoadTask?.cancel()
        windowLoadTask = Task {
            do {
                let payload = try await ResearchReportTreeSource.load(
                    localRef: artifact.localRef,
                    focusedComponentID: componentID,
                    windowRadius: Self.chapterWindowRadius
                )
                try Task.checkCancellation()
                guard token == loadToken,
                      selectedComponentID == componentID else { return }
                let snapshot = scrollAnchorCoordinator.capture()
                let result = document.apply(
                    payload,
                    focusedAt: componentID
                )
                if result.prependedChapters {
                    await scrollAnchorCoordinator.restoreAfterPrepending(snapshot)
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
        behavior: ResearchReportNavigationBehavior,
        chapterOffset: CGFloat = 0
    ) {
        scrollToken &+= 1
        pendingComponentID = componentID
        let token = scrollToken
        scrollRequest = ResearchReportScrollRequest(
            componentID: componentID,
            token: token,
            behavior: behavior,
            chapterOffset: chapterOffset
        )
    }

    func rememberedChapterID(in outlineIDs: [String]) -> String? {
        let candidates = [
            tabSession.readingAnchor?.componentID,
            tabSession.selectedChapterID.isEmpty
                ? nil : tabSession.selectedChapterID,
        ]
        return candidates.compactMap { $0 }.first {
            outlineIDs.contains($0)
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

    private static var chapterWindowRadius: Int {
        ResearchReportChapterWindow.navigationRadius
    }
}
