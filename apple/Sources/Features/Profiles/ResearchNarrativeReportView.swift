import SwiftUI

struct ResearchNarrativeReportView: View {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let steps: [ResearchTransitionStep]
    let nextCursor: String?
    let profileName: String
    let auditCacheNamespace: String
    let reportTitle: String
    let artifact: ResearchArtifactModel?
    let selectBranch: (String) -> Void
    let loadEarlier: () async -> Void
    let loadHistory: ([String]) async -> Void
    let loadAuditObject: (String) async throws -> ResearchAuditObjectPayload

    @State private var sections: [ResearchJournalSection] = []
    @State private var reportError: String?
    @State private var selectedCheckpointRef = ""
    @State private var sectionRefsByCheckpoint: [String: String] = [:]
    @State private var programmaticScrollToken: UUID?
    @State private var selectedAudit: ResearchAuditSelection?
    @StateObject private var auditCache = ResearchAuditObjectCache()

    var body: some View {
        HStack(spacing: 0) {
            ResearchVersionTreePane(
                detail: detail,
                workPackage: workPackage,
                steps: orderedSteps,
                sectionRefsByCheckpoint: sectionRefsByCheckpoint,
                selectedCheckpointRef: $selectedCheckpointRef,
                select: selectCheckpoint,
                loadEarlier: loadEarlier,
                canLoadEarlier: nextCursor != nil
            )
            .frame(width: ResearchTreeLayout.navigatorWidth)
            .clipped()
            Divider()
            report
        }
        .popover(item: $selectedAudit) { selection in
            ResearchAuditPopover(
                selection: selection,
                detail: detail,
                steps: steps,
                cache: auditCache,
                cacheNamespace: auditCacheNamespace,
                loadObject: loadAuditObject
            )
        }
        .task(id: reportLoadIdentity) {
            await loadReport()
        }
    }

    private var reportLoadIdentity: String {
        ([artifact?.journalHash ?? ""] + steps.map {
            "\($0.stepRef)|\($0.edgeRef)|\($0.toNode)"
        }).joined(separator: "\u{1f}")
    }

    private var report: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    reportHeader
                    if let reportError {
                        VStack(spacing: 10) {
                            Image(systemName: "doc.text.magnifyingglass")
                                .font(.largeTitle)
                            Text("完整报告暂不可用")
                                .font(.headline)
                            Text(reportError)
                                .foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 64)
                    } else if sections.isEmpty {
                        ProgressView("正在校验并读取中文研究报告…")
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 64)
                    } else {
                        ForEach(Array(sections.enumerated()), id: \.element.id) {
                            index, section in
                            positionedSection(
                                section,
                                compact: index > 0
                                    && sections[index - 1].checkpointRef
                                        == section.checkpointRef
                            )
                        }
                    }
                }
                .frame(maxWidth: 820, alignment: .leading)
                .padding(.horizontal, 42)
                .padding(.bottom, 56)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .coordinateSpace(name: "research-report-scroll")
            .onPreferenceChange(ResearchReportSectionPositionKey.self) {
                positions in
                guard programmaticScrollToken == nil else { return }
                guard let sectionRef = ResearchReportScrollResolver
                    .activeSectionRef(positions: positions, viewportTop: 24),
                    let section = sections.first(where: {
                        $0.sectionRef == sectionRef
                    }), selectedCheckpointRef != section.checkpointRef else {
                    return
                }
                selectedCheckpointRef = section.checkpointRef
            }
            .onChange(of: selectedCheckpointRef) { checkpointRef in
                // Passive viewport tracking updates the tree selection while
                // the user scrolls. Only an explicit tree click owns a token
                // and is allowed to scroll the report programmatically.
                guard ResearchReportNavigation.shouldScrollReport(
                    hasProgrammaticToken: programmaticScrollToken != nil
                ) else { return }
                guard let sectionRef = ResearchReportNavigation.scrollTarget(
                    checkpointRef: checkpointRef,
                    sectionRefsByCheckpoint: sectionRefsByCheckpoint
                )
                else { return }
                withAnimation(.easeInOut(duration: 0.22)) {
                    proxy.scrollTo(sectionRef, anchor: .top)
                }
                guard let token = programmaticScrollToken else { return }
                Task { @MainActor in
                    try? await Task.sleep(nanoseconds: 350_000_000)
                    if programmaticScrollToken == token {
                        programmaticScrollToken = nil
                    }
                }
            }
        }
    }

    private var reportHeader: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(reportTitle)
                    .font(.largeTitle.weight(.bold))
                Text(statusLabel(detail.status))
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 9)
                    .padding(.vertical, 4)
                    .background(statusTint.opacity(0.12), in: Capsule())
                    .foregroundStyle(statusTint)
                Spacer()
            }
            Text(
                "由 \(profileName) 负责 · 当前阶段："
                    + ResearchDisplayText.node(detail.currentNode)
            )
                .font(.callout)
                .foregroundStyle(.secondary)
            Text("以下正文由研究 Agent 在各检查点提交，并与相应证据和义务变化绑定。")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 34)
        .padding(.bottom, 28)
    }

    private func narrativeSection(
        _ section: ResearchJournalSection,
        compact: Bool = false,
        titleOverride: String? = nil
    ) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if section.displayKind == "graph_continuation" {
                Label(
                    "图版本承接 / 重新进入审查",
                    systemImage: "arrow.triangle.branch"
                )
                .font(.caption.weight(.semibold))
                .foregroundStyle(.indigo)
            }
            if !compact {
                HStack(spacing: 8) {
                    Text(stageLabel(for: section))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Color.accentColor)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(Color.accentColor.opacity(0.1), in: Capsule())
                    Text(section.graphRef)
                        .font(.caption2.weight(.medium))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.secondary.opacity(0.08), in: Capsule())
                    if let occurredAt = section.researchOccurredAt {
                        Text("研究发生于")
                        Text(Date(timeIntervalSince1970: occurredAt), style: .date)
                        Text(Date(timeIntervalSince1970: occurredAt), style: .time)
                        Text("· 登记于")
                    }
                    Text(Date(timeIntervalSince1970: section.createdAt), style: .date)
                    if section.researchOccurredAt != nil {
                        Text(Date(timeIntervalSince1970: section.createdAt), style: .time)
                    }
                    Text("·")
                    Text(shortReference(section.checkpointRef))
                        .monospaced()
                }
                .font(.caption)
                .foregroundStyle(.tertiary)
            }

            Text(titleOverride ?? section.title)
                .font(compact ? .headline : .title2.weight(.semibold))
                .foregroundStyle(.primary)
            if !section.body.isEmpty {
                reportParagraph(section.body, linkIDs: [], section: section)
            }
            if !section.blocks.isEmpty {
                ForEach(Array(section.blocks.enumerated()), id: \.offset) {
                    _, block in
                    VStack(alignment: .leading, spacing: 6) {
                        if let timing = block.reportTiming {
                            HStack(spacing: 4) {
                                Text("本条报告形成于")
                                Text(
                                    Date(timeIntervalSince1970: timing.occurredAt),
                                    style: .date
                                )
                                Text(
                                    Date(timeIntervalSince1970: timing.occurredAt),
                                    style: .time
                                )
                            }
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                        }
                        reportBlock(block, section: section)
                    }
                }
            }

            if let entryResolution = transitionStep(for: section)?.entryResolution {
                ResearchEntryResolutionView(value: entryResolution)
            }

            obligationTable(section)

            if !readableUnboundLinks(in: section).isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 7) {
                        ForEach(readableUnboundLinks(in: section)) { link in
                            auditChip(link, section: section)
                        }
                    }
                    .padding(.vertical, 2)
                }
            }
            if !missingPresentationLinks(in: section).isEmpty {
                DisclosureGroup(
                    "审计待补：\(missingPresentationLinks(in: section).count) 项证据缺少中文说明"
                ) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("这些引用仍保留在可信 journal 中，但在补齐历史 presentation metadata 前不会污染研究正文。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        ForEach(missingPresentationLinks(in: section)) { link in
                            auditChip(
                                link,
                                section: section,
                                displayLabel: "待补证据说明"
                            )
                        }
                    }
                    .padding(.top, 6)
                }
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            }
            Divider().padding(.top, compact ? 8 : 18)
        }
        .padding(.horizontal, section.displayKind == "graph_continuation" ? 14 : 0)
        .padding(.top, section.displayKind == "graph_continuation" ? 12 : 0)
        .background(
            section.displayKind == "graph_continuation"
                ? Color.indigo.opacity(0.06) : Color.clear,
            in: RoundedRectangle(cornerRadius: 10)
        )
        .padding(.bottom, compact ? 12 : 24)
        .contentShape(Rectangle())
        .onTapGesture {
            selectedCheckpointRef = section.checkpointRef
        }
        .accessibilityIdentifier("research.report.section.\(section.sectionID)")
    }

    private func positionedSection(
        _ section: ResearchJournalSection,
        compact: Bool = false,
        titleOverride: String? = nil
    ) -> some View {
        narrativeSection(
            section,
            compact: compact,
            titleOverride: titleOverride
        )
            .id(section.sectionRef)
            .background {
                GeometryReader { geometry in
                    Color.clear.preference(
                        key: ResearchReportSectionPositionKey.self,
                        value: [section.sectionRef: geometry.frame(
                            in: .named("research-report-scroll")
                        ).minY]
                    )
                }
            }
    }

    private func reportParagraph(
        _ text: String,
        linkIDs: [String],
        section: ResearchJournalSection
    ) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            reportRichText(text)
            if !linkIDs.isEmpty {
                HStack(spacing: 6) {
                    ForEach(readableAuditLinks(in: section).filter {
                        linkIDs.contains($0.linkID)
                    }) {
                        link in
                        auditChip(link, section: section)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func reportRichText(_ text: String) -> some View {
        if ResearchReportTextProjection.containsMath(text) {
            RenderedInlineMathTextView(text: text)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            Text(markdownInline(text))
                .font(.body)
                .lineSpacing(6)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func markdownInline(_ text: String) -> AttributedString {
        (try? AttributedString(
            markdown: text,
            options: .init(
                interpretedSyntax: .inlineOnlyPreservingWhitespace
            )
        )) ?? AttributedString(text)
    }

    @ViewBuilder
    private func reportBlock(
        _ block: ResearchJournalBlock,
        section: ResearchJournalSection
    ) -> some View {
        switch block.kind {
        case "math":
            VStack(alignment: .leading, spacing: 8) {
                Label("因子公式", systemImage: "function")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color.accentColor)
                Text(block.fallback ?? "因子公式")
                    .font(.callout)
                RenderedMathFormulaView(
                    latex: block.latex ?? "",
                    fallback: block.fallback ?? "因子公式"
                )
                .background(
                    Color.secondary.opacity(0.07),
                    in: RoundedRectangle(cornerRadius: 7)
                )
                DisclosureGroup("公式源码（审计）") {
                    Text(block.latex ?? "")
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .padding(.top, 6)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .font(.caption.weight(.medium))
                HStack(spacing: 6) {
                    ForEach(readableAuditLinks(in: section).filter {
                        block.linkIDs.contains($0.linkID)
                    }) { link in
                        auditChip(link, section: section)
                    }
                }
            }
        case "figure":
            if let asset = block.asset, let reportRef = artifact?.localRef {
                VStack(alignment: .leading, spacing: 8) {
                    ResearchReportImageView(
                        asset: asset,
                        reportRef: reportRef
                    )
                    HStack(spacing: 6) {
                        ForEach(readableAuditLinks(in: section).filter {
                            block.linkIDs.contains($0.linkID)
                        }) { link in
                            auditChip(link, section: section)
                        }
                    }
                }
            } else {
                Label(
                    "本条图像缺少可信的本地报告引用。",
                    systemImage: "photo.badge.exclamationmark"
                )
                .font(.callout)
                .foregroundStyle(.secondary)
            }
        case "paragraph":
            reportParagraph(
                block.text ?? "",
                linkIDs: block.linkIDs,
                section: section
            )
        case "list":
            VStack(alignment: .leading, spacing: 10) {
                ForEach(Array(block.rows.enumerated()), id: \.offset) {
                    _, row in
                    HStack(alignment: .top, spacing: 9) {
                        Text("•")
                            .foregroundStyle(.secondary)
                        VStack(alignment: .leading, spacing: 6) {
                            reportRichText(row.text ?? "")
                            rowChips(row, section: section)
                        }
                    }
                }
            }
        case "table":
            reportTable(block, section: section)
        default:
            EmptyView()
        }
    }

    private func reportTable(
        _ block: ResearchJournalBlock,
        section: ResearchJournalSection
    ) -> some View {
        ScrollView(.horizontal, showsIndicators: true) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 0) {
                    ForEach(block.columns, id: \.self) { column in
                        Text(column)
                            .font(.caption.weight(.semibold))
                            .frame(width: 132, alignment: .leading)
                            .padding(8)
                    }
                    Text("依据")
                        .font(.caption.weight(.semibold))
                        .frame(width: 170, alignment: .leading)
                        .padding(8)
                }
                .background(Color.secondary.opacity(0.08))
                ForEach(Array(block.rows.enumerated()), id: \.offset) {
                    index, row in
                    HStack(alignment: .top, spacing: 0) {
                        ForEach(Array(row.cells.enumerated()), id: \.offset) {
                            _, cell in
                            Text(cell)
                                .font(.callout)
                                .textSelection(.enabled)
                                .frame(width: 132, alignment: .leading)
                                .padding(8)
                        }
                        rowChips(row, section: section)
                            .frame(width: 170, alignment: .leading)
                            .padding(8)
                    }
                    .background(
                        index.isMultiple(of: 2)
                            ? Color.clear
                            : Color.secondary.opacity(0.035)
                    )
                }
            }
            .overlay {
                RoundedRectangle(cornerRadius: 7)
                    .stroke(Color.secondary.opacity(0.18), lineWidth: 1)
            }
        }
    }

    private func rowChips(
        _ row: ResearchJournalRow,
        section: ResearchJournalSection
    ) -> some View {
        HStack(spacing: 6) {
            ForEach(links(for: row, in: section)) { link in
                auditChip(link, section: section)
            }
        }
    }

    private func links(
        for row: ResearchJournalRow,
        in section: ResearchJournalSection
    ) -> [ResearchJournalLink] {
        let ids = Set(row.linkIDs)
        return readableAuditLinks(in: section).filter {
            ids.contains($0.linkID)
        }
    }

    private func unboundLinks(
        in section: ResearchJournalSection
    ) -> [ResearchJournalLink] {
        let bound = Set(
            section.blocks.flatMap { block in
                block.linkIDs + block.rows.flatMap(\.linkIDs)
            }
        )
        return auditLinks(in: section).filter { !bound.contains($0.linkID) }
    }

    private func readableUnboundLinks(
        in section: ResearchJournalSection
    ) -> [ResearchJournalLink] {
        let readable = Set(readableAuditLinks(in: section).map(\.linkID))
        return unboundLinks(in: section).filter {
            readable.contains($0.linkID)
        }
    }

    private func readableAuditLinks(
        in section: ResearchJournalSection
    ) -> [ResearchJournalLink] {
        let step = ResearchJournalPresentation.obligationSnapshotStep(
            for: section,
            steps: steps
        )
        return auditLinks(in: section).filter { link in
            link.kind != "evidence"
                || ResearchJournalPresentation.hasReadableEvidencePresentation(
                    link,
                    in: step?.evidencePresentations ?? []
                )
        }
    }

    private func missingPresentationLinks(
        in section: ResearchJournalSection
    ) -> [ResearchJournalLink] {
        let readable = Set(readableAuditLinks(in: section).map(\.linkID))
        return auditLinks(in: section).filter {
            $0.kind == "evidence" && !readable.contains($0.linkID)
        }
    }

    private func auditLinks(
        in section: ResearchJournalSection
    ) -> [ResearchJournalLink] {
        section.links.filter { !["obligation", "delta"].contains($0.kind) }
    }

    private func auditChip(
        _ link: ResearchJournalLink,
        section: ResearchJournalSection,
        displayLabel: String? = nil
    ) -> some View {
        let step = steps.first { $0.stepRef == section.auditCheckpointRef }
        let label = displayLabel ?? ResearchJournalPresentation.chipLabel(
            link,
            sectionTitle: section.title,
            obligations: detail.researchCycle.obligations,
            obligationPresentations: step?.obligationPresentations ?? [],
            evidencePresentations: step?.evidencePresentations ?? []
        )
        return Button {
            selectedAudit = ResearchAuditSelection(
                link: link,
                checkpointRef: section.auditCheckpointRef,
                displayLabel: label
            )
        } label: {
            Label(label, systemImage: chipIcon(link.kind))
                .font(.caption.weight(.medium))
                .lineLimit(2)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 280, alignment: .leading)
        }
        .buttonStyle(.bordered)
        .controlSize(.mini)
        .accessibilityIdentifier(
            "research.report.chip.\(link.kind).\(link.linkID)"
        )
    }

    @ViewBuilder
    private func obligationTable(
        _ section: ResearchJournalSection
    ) -> some View {
        let groups = stageObligationRows(in: section)
        if !groups.active.isEmpty || !groups.inherited.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Text("本阶段新增或变化的研究义务")
                    .font(.headline)
                if groups.active.isEmpty {
                    Text("本阶段没有新增义务，也没有义务状态发生变化。")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                } else {
                    obligationRowsTable(groups.active, section: section)
                }
                if !groups.inherited.isEmpty {
                    DisclosureGroup("沿用义务（\(groups.inherited.count)）") {
                        obligationRowsTable(
                            groups.inherited,
                            section: section
                        )
                        .padding(.top, 8)
                    }
                    .font(.callout.weight(.medium))
                }
            }
            .padding(.top, 6)
        }
    }

    private func obligationRowsTable(
        _ rows: [ResearchObligationTableRow],
        section: ResearchJournalSection
    ) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            obligationHeader
            ForEach(Array(rows.enumerated()), id: \.element.id) {
                index, row in
                obligationRow(row, section: section)
                    .background(
                        index.isMultiple(of: 2)
                            ? Color.clear
                            : Color.secondary.opacity(0.035)
                    )
            }
        }
        .overlay(alignment: .bottom) {
            Rectangle().fill(Color.secondary.opacity(0.18)).frame(height: 1)
        }
    }

    private var obligationHeader: some View {
        HStack(spacing: 10) {
            Text("研究义务").frame(maxWidth: .infinity, alignment: .leading)
            Text("重要性").frame(width: 54, alignment: .leading)
            Text("本步骤变化").frame(width: 112, alignment: .leading)
            Text("当前").frame(width: 64, alignment: .leading)
            Text("审计").frame(width: 116, alignment: .leading)
        }
        .font(.caption.weight(.semibold))
        .foregroundStyle(.secondary)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(Color.secondary.opacity(0.08))
    }

    private func obligationRow(
        _ row: ResearchObligationTableRow,
        section: ResearchJournalSection
    ) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(row.question)
                .font(.callout)
                .lineLimit(3)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(row.materiality)
                .frame(width: 54, alignment: .leading)
            Text(row.change)
                .frame(width: 112, alignment: .leading)
            Text(row.currentStatus)
                .frame(width: 64, alignment: .leading)
            HStack(spacing: 5) {
                auditChip(
                    row.obligationLink,
                    section: section,
                    displayLabel: "问题详情"
                )
                if let delta = row.deltaLink {
                    auditChip(
                        delta,
                        section: section,
                        displayLabel: "变化依据"
                    )
                }
            }
            .frame(width: 116, alignment: .leading)
        }
        .font(.caption)
        .padding(.horizontal, 10)
        .padding(.vertical, 10)
    }

    private func obligationRows(
        in section: ResearchJournalSection
    ) -> [ResearchObligationTableRow] {
        let step = ResearchJournalPresentation.obligationSnapshotStep(
            for: section,
            steps: steps
        )
        return ResearchJournalPresentation.obligationRows(
            links: section.links,
            checkpointObligationRefs: step?.obligationRefs,
            obligations: detail.researchCycle.obligations,
            obligationPresentations: step?.obligationPresentations ?? [],
            changes: step?.obligationChanges ?? [],
            statusOverrides: ResearchJournalPresentation.obligationStatuses(
                at: section.checkpointRef,
                steps: orderedSteps,
                currentObligations: detail.researchCycle.obligations
            )
        )
    }

    private func stageObligationRows(
        in section: ResearchJournalSection
    ) -> ResearchStageObligationRows {
        guard let snapshot = ResearchJournalPresentation.obligationSnapshotStep(
            for: section,
            steps: orderedSteps
        ), let index = orderedSteps.firstIndex(where: {
            $0.stepRef == snapshot.stepRef
        }) else {
            return ResearchStageObligationRows(
                active: obligationRows(in: section), inherited: []
            )
        }
        let step = orderedSteps[index]
        let previousRefs = index > 0
            ? orderedSteps[index - 1].obligationRefs : nil
        return ResearchJournalPresentation.stageObligationRows(
            rows: obligationRows(in: section),
            currentRefs: step.obligationRefs,
            previousRefs: previousRefs,
            changes: step.obligationChanges
        )
    }

    private func stageLabel(for section: ResearchJournalSection) -> String {
        let step = transitionStep(for: section)
        return ResearchDisplayText.node(step?.toNode ?? detail.currentNode)
    }

    private func transitionStep(
        for section: ResearchJournalSection
    ) -> ResearchTransitionStep? {
        steps.first { $0.stepRef == section.checkpointRef }
    }

    private func loadReport() async {
        guard let artifact, !artifact.journalRef.isEmpty else {
            sections = []
            reportError = "报告未按新协议完成，需重做：本地记录缺少 JOURNAL.json，没有经过校验的中文 journal。请让对应 research Agent 从可信 root 重新提交该分支的 checkpoint；客户端不会用旧 REPORT.md 或 INDEX.json 冒充完整报告。"
            return
        }
        do {
            async let documentTask = ResearchJournalLoader.load(
                artifact: artifact
            )
            async let indexTask = ResearchReportIndex.loadVerified(
                artifact: artifact
            )
            let (document, indexSections) = try await (
                documentTask, indexTask
            )
            let loadedSections = try ResearchJournalPresentation.displaySections(
                in: document,
                indexedBy: indexSections,
                transitions: steps
            )
                .sorted {
                    if $0.createdAt != $1.createdAt {
                        return $0.createdAt < $1.createdAt
                    }
                    return $0.id < $1.id
                }
            sections = loadedSections
            await loadHistory(Array(Set(
                loadedSections.flatMap {
                    [$0.checkpointRef, $0.auditCheckpointRef]
                }
            )))
            sectionRefsByCheckpoint = Dictionary(
                loadedSections.map { ($0.checkpointRef, $0.sectionRef) },
                uniquingKeysWith: { first, _ in first }
            )
            reportError = nil
            selectedCheckpointRef = ResearchReportNavigation.reconciledSelection(
                currentCheckpointRef: selectedCheckpointRef,
                availableCheckpointRefs: loadedSections.map(\.checkpointRef)
            )
        } catch {
            sections = []
            sectionRefsByCheckpoint = [:]
            reportError = error.localizedDescription
        }
    }

    private var orderedSteps: [ResearchTransitionStep] {
        steps.filter(
            ResearchTimelineProjection.isGraphNodeTransition
        ).sorted {
            if $0.createdAt != $1.createdAt { return $0.createdAt < $1.createdAt }
            return $0.id < $1.id
        }
    }

    private func selectCheckpoint(_ checkpointRef: String, _ branchID: String) {
        programmaticScrollToken = UUID()
        if ResearchBranchNavigation.requiresReload(
            currentBranchRef: detail.branchRef,
            targetBranchID: branchID
        ) {
            selectBranch(branchID)
        }
        selectedCheckpointRef = checkpointRef
    }

    private var statusTint: Color {
        switch detail.status {
        case "completed", "closed": return .green
        case "paused", "blocked": return .orange
        case "failed": return .red
        default: return .blue
        }
    }
}

enum ResearchTimelineProjection {
    /// Synthetic audit/report carriers belong in the narrative attached to
    /// their substantive checkpoint, never in the graph-node version tree.
    ///
    /// The transition projection does not yet expose checkpoint lineage/type,
    /// so these protocol-defined synthetic edges are the narrow fallback.
    /// Prefer the structured lineage field here once the server projects it.
    private static let syntheticCarrierEdges: Set<String> = [
        "graph-edge:__current_node_report__",
        "graph-edge:__graph_continuation__",
    ]

    static func isGraphNodeTransition(
        _ step: ResearchTransitionStep
    ) -> Bool {
        !syntheticCarrierEdges.contains(step.edgeRef)
    }
}

enum ResearchBranchNavigation {
    static func requiresReload(
        currentBranchRef: String,
        targetBranchID: String
    ) -> Bool {
        let currentBranchID = currentBranchRef.split(separator: ":")
            .last.map(String.init) ?? currentBranchRef
        return !targetBranchID.isEmpty && targetBranchID != currentBranchID
    }
}

enum ResearchReportNavigation {
    static func shouldScrollReport(hasProgrammaticToken: Bool) -> Bool {
        hasProgrammaticToken
    }

    static func scrollTarget(
        checkpointRef: String,
        sectionRefsByCheckpoint: [String: String]
    ) -> String? {
        sectionRefsByCheckpoint[checkpointRef]
    }

    static func reconciledSelection(
        currentCheckpointRef: String,
        availableCheckpointRefs: [String]
    ) -> String {
        if availableCheckpointRefs.contains(currentCheckpointRef) {
            return currentCheckpointRef
        }
        return availableCheckpointRefs.last ?? ""
    }
}

struct ResearchReportSectionPositionKey: PreferenceKey {
    static var defaultValue: [String: CGFloat] = [:]

    static func reduce(
        value: inout [String: CGFloat],
        nextValue: () -> [String: CGFloat]
    ) {
        value.merge(nextValue(), uniquingKeysWith: { _, next in next })
    }
}

enum ResearchReportScrollResolver {
    static func activeSectionRef(
        positions: [String: CGFloat],
        viewportTop: CGFloat
    ) -> String? {
        guard !positions.isEmpty else { return nil }
        let atOrAbove = positions.filter { $0.value <= viewportTop }
        if let nearest = atOrAbove.max(by: { $0.value < $1.value }) {
            return nearest.key
        }
        return positions.min(by: { $0.value < $1.value })?.key
    }
}

private struct ResearchAuditSelection: Identifiable {
    let link: ResearchJournalLink
    let checkpointRef: String
    let displayLabel: String
    var id: String { "\(checkpointRef)|\(link.id)" }
}

private struct ResearchAuditPopover: View {
    let selection: ResearchAuditSelection
    let detail: ProfileResearchDetail
    let steps: [ResearchTransitionStep]
    let cache: ResearchAuditObjectCache
    let cacheNamespace: String
    let loadObject: (String) async throws -> ResearchAuditObjectPayload

    @State private var object: ResearchAuditObjectPayload?
    @State private var error: String?

    private var step: ResearchTransitionStep? {
        steps.first { $0.stepRef == selection.checkpointRef }
    }

    private var objectHref: String? {
        step?.objectHref(
            kind: selection.link.kind,
            targetRef: selection.link.targetRef
        )
    }

    var body: some View {
        ViewThatFits(in: .vertical) {
            popoverContent
                .fixedSize(horizontal: false, vertical: true)
            ScrollView {
                popoverContent
            }
        }
        .frame(minWidth: 420, idealWidth: 500, maxWidth: 560)
        .frame(maxHeight: 620)
        .task(id: selection.id) {
            await loadSelectedObject()
        }
    }

    private var popoverContent: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(
                selection.displayLabel,
                systemImage: chipIcon(selection.link.kind)
            )
            .font(.headline)
            .lineLimit(nil)
            .fixedSize(horizontal: false, vertical: true)
            Text(ResearchDisplayText.auditPurpose(selection.link.kind))
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if let step {
                Divider()
                LabeledContent(
                    "研究阶段",
                    value: "\(ResearchDisplayText.node(step.fromNode)) → "
                        + ResearchDisplayText.node(step.toNode)
                )
                objectDetail
                auditIdentifiers(step)
            } else {
                Text("该报告段落没有可验证的检查点，无法读取历史审计对象。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(18)
    }

    @ViewBuilder
    private var objectDetail: some View {
        if let object {
            Divider()
            if let question = object.epistemicQuestion {
                Text(question)
                    .font(.callout)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let kind = object.obligationKind {
                LabeledContent("义务类型", value: kind)
            }
            if let kind = object.objectKind {
                LabeledContent("变化对象", value: kind)
            }
            if let fromState = object.fromState, let toState = object.toState {
                LabeledContent("状态变化", value: "\(fromState) → \(toState)")
            }
            if let deltaRef = object.deltaRef {
                LabeledContent("变化引用") {
                    Text(deltaRef)
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                }
            }
            if let status = object.status {
                LabeledContent("检查点状态", value: status)
            }
            LabeledContent("对象协议", value: String(object.schemaVersion))
            if let envelopeID = object.envelopeID {
                LabeledContent("证据包 ID", value: envelopeID)
            }
            if let envelopeHash = object.envelopeHash {
                LabeledContent("证据包哈希") {
                    Text(envelopeHash)
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                }
            }
            if let materiality = object.materiality {
                LabeledContent("重要性", value: materiality)
            }
            if let claimType = object.claimType {
                LabeledContent("主张类型", value: claimType)
            }
            if let evidenceState = object.evidenceState {
                LabeledContent("证据状态", value: evidenceState)
            }
            if let createdEventRef = object.createdEventRef {
                LabeledContent("创建事件") {
                    Text(createdEventRef)
                        .font(.caption.monospaced())
                        .lineLimit(2)
                }
            }
            if let trialPlanID = object.trialPlanID {
                LabeledContent("试验计划", value: trialPlanID)
            }
            if let trialFamily = object.trialFamily {
                LabeledContent("试验族", value: trialFamily)
            }
            if let version = object.trialPlanVersion {
                LabeledContent("计划版本", value: String(version))
            }
            if let hypothesisRef = object.hypothesisRef {
                LabeledContent("研究假设", value: hypothesisRef)
            }
            if let protocolRef = object.protocolRef {
                LabeledContent("检验协议", value: protocolRef)
            }
            if let outcomes = object.outcomes {
                referenceValues("主要结果", outcomes.primary)
                referenceValues("次要结果", outcomes.secondary)
            }
            if let roles = object.sampleRoles, !roles.isEmpty {
                referenceValues(
                    "样本阶段",
                    roles.map { "\($0.role) · \($0.sampleRef)" }
                )
            }
            if let kind = object.evidenceKind {
                LabeledContent("证据类型", value: kind)
            }
            if let count = object.hypothesesTested {
                LabeledContent("已检验假设数", value: String(count))
            }
            if let runID = object.runID {
                LabeledContent("试验运行", value: runID)
            }
            if let configurationID = object.configurationID,
               let revision = object.configurationRevision {
                LabeledContent(
                    "运行配置",
                    value: "\(configurationID) · r\(revision)"
                )
            }
            if let role = object.trialRole, !role.isEmpty {
                LabeledContent("试验角色", value: role)
            }
            if let stage = object.trialStage, !stage.isEmpty {
                LabeledContent("试验阶段", value: stage)
            }
            if let comparison = object.comparisonID, !comparison.isEmpty {
                LabeledContent("对比组", value: comparison)
            }
            if let sample = object.sampleRef, !sample.isEmpty {
                LabeledContent("样本定义", value: sample)
            }
            if let start = object.sampleStart, let end = object.sampleEnd,
               !start.isEmpty || !end.isEmpty {
                LabeledContent("样本时间", value: "\(start) — \(end)")
            }
            if let hash = object.runSpecHash {
                LabeledContent("RunSpec 哈希") {
                    Text(hash)
                        .font(.caption.monospaced())
                        .textSelection(.enabled)
                }
            }
            if let version = object.runSpecVersion {
                LabeledContent("RunSpec 协议", value: String(version))
            }
            if let runSpec = object.runSpecJSON, !runSpec.isEmpty {
                DisclosureGroup("完整冻结运行配置") {
                    ScrollView([.horizontal, .vertical]) {
                        Text(runSpec)
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 320)
                    .padding(.top, 8)
                }
            }
            referenceValues("指标引用", object.metricRefs ?? [])
            referenceValues("产物引用", object.artifactRefs ?? [])
            referenceValues("来源引用", object.sourceRefs ?? [])
            if let stopCondition = object.stopCondition {
                LabeledContent("停止条件", value: stopCondition)
            }
            referenceValues("证据限制", object.limitations ?? [])
            referenceValues("证据冲突", object.conflicts ?? [])
        } else if let error {
            Text(error)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        } else if objectHref != nil {
            ProgressView("正在读取该检查点的审计对象…")
                .controlSize(.small)
        } else {
            Text(
                "此记录的中文摘要已显示在上方；当前检查点未提供更细的对象投影。"
                    + "技术引用仍保留在下方，供审计和重放使用。"
            )
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func auditIdentifiers(
        _ step: ResearchTransitionStep
    ) -> some View {
        DisclosureGroup("审计标识（高级）") {
            VStack(alignment: .leading, spacing: 8) {
                auditReference("稳定引用", selection.link.targetRef)
                auditReference("对应检查点", selection.checkpointRef)
                auditReference("图边", step.edgeRef)
            }
            .padding(.top, 8)
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func auditReference(
        _ title: String,
        _ value: String
    ) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption.weight(.semibold))
            Text(value)
                .font(.caption.monospaced())
                .textSelection(.enabled)
        }
    }

    @ViewBuilder
    private func referenceValues(
        _ title: String,
        _ values: [String]
    ) -> some View {
        if !values.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                ForEach(values, id: \.self) { value in
                    Text("• \(value)")
                        .font(.caption)
                        .textSelection(.enabled)
                }
            }
        }
    }

    private func loadSelectedObject() async {
        object = nil
        error = nil
        guard let objectHref else { return }
        do {
            object = try await cache.load(
                namespace: cacheNamespace,
                href: objectHref,
                using: loadObject
            )
        } catch is CancellationError {
            return
        } catch {
            self.error = "无法读取该检查点的审计对象：\(error.localizedDescription)"
        }
    }
}

enum ResearchDisplayText {
    static func reportRequirement(_ requirementID: String) -> String? {
        switch requirementID.split(separator: ".").last.map(String.init) {
        case "expression_identity": return "原公式、参数与版本"
        case "observable_meaning_direction_units":
            return "可观察含义、方向、单位与数值域"
        case "timing_and_causality": return "时序与因果可用性"
        case "alternatives_and_falsifiers": return "替代解释与可证伪条件"
        case "behavioral_mechanism": return "行为机制"
        case "boundary_conditions": return "适用边界与市场环境"
        case "microstructure_channel": return "微观结构渠道"
        case "participant_ecology": return "市场参与者生态"
        case "risk_transfer_and_fundamentals": return "风险转移与基本面机制"
        case "conditioning_semantics": return "条件化信号的研究语义"
        case "parameterization_and_derivation": return "参数化与派生因子"
        default: return nil
        }
    }

    static func reportTitle(_ title: String) -> String {
        guard title.range(
            of: "\\p{Han}",
            options: .regularExpression
        ) != nil else {
            return "因子研究报告"
        }
        return title
    }

    static func linkKind(_ kind: String) -> String {
        switch kind {
        case "checkpoint": return "检查点"
        case "trial_plan": return "试验计划"
        case "obligation": return "研究义务"
        case "claim": return "证据状态"
        case "evidence": return "证据"
        case "job": return "计算任务"
        case "run": return "试验运行"
        case "delta": return "状态变化"
        case "profile_handoff": return "研究转接"
        default: return "审计对象"
        }
    }

    static func auditPurpose(_ kind: String) -> String {
        switch kind {
        case "checkpoint": return "说明这段研究叙事对应哪一次可信检查点。"
        case "trial_plan": return "说明本步骤准备回答什么问题，以及样本、范围和停止条件。"
        case "obligation": return "说明研究仍需回答的问题、重要性和当前收敛程度。"
        case "claim": return "说明当前研究主张获得了什么程度的证据支持。"
        case "evidence": return "说明本步骤取得的结果、指标、产物、限制和冲突。"
        case "job": return "说明后端计算任务的状态、输入规范和可追溯结果。"
        case "run": return "说明一次试验运行的范围、状态和结果产物。"
        case "delta": return "说明证据为何使研究义务或主张发生状态变化。"
        case "profile_handoff": return "说明研究由谁转接、转接了哪些范围与检查点。"
        default: return "说明本步骤正文所引用的可审计研究对象。"
        }
    }

    static func branchLabel(
        _ label: String,
        currentNode: String
    ) -> String {
        if label.range(of: "\\p{Han}", options: .regularExpression) != nil {
            return label
        }
        return "\(node(currentNode))研究"
    }

    static func node(_ node: String) -> String {
        switch node {
        case "candidate_discovery": return "候选发现"
        case "hypothesis_preregistration": return "假设预注册"
        case "capability_resolution": return "研究能力确认"
        case "data_contract": return "数据契约"
        case "factor_semantics": return "因子语义"
        case "validation_design": return "验证设计"
        case "trial_plan": return "试验计划"
        case "capability_gap": return "能力缺口"
        case "job_evidence_ready": return "回测证据就绪"
        case "evidence_assessment": return "证据评估"
        case "factor_improvement": return "因子改进"
        case "completed": return "研究完成"
        default: return "研究进行中"
        }
    }

    static func productGroup(_ productGroup: String) -> String {
        switch productGroup.lowercased() {
        case "china_futures", "cnfutures": return "中国期货"
        case "china_equities", "cnequities": return "中国股票"
        case "japan_futures", "jpfutures": return "日本期货"
        default: return "其他产品组"
        }
    }
}

private func chipIcon(_ kind: String) -> String {
    switch kind {
    case "trial_plan": return "list.bullet.clipboard"
    case "obligation": return "questionmark.circle"
    case "claim": return "checkmark.seal"
    case "evidence": return "doc.text.magnifyingglass"
    case "job", "run": return "gearshape.2"
    case "delta": return "arrow.left.arrow.right"
    case "profile_handoff": return "person.2.arrow.trianglehead.counterclockwise"
    default: return "point.3.connected.trianglepath.dotted"
    }
}

private func shortReference(_ value: String) -> String {
    let suffix = value.split(separator: ":").last.map(String.init) ?? value
    return suffix.count > 18
        ? "\(suffix.prefix(8))…\(suffix.suffix(6))"
        : suffix
}

private func statusLabel(_ status: String) -> String {
    switch status {
    case "running": return "进行中"
    case "paused": return "已暂停"
    case "completed", "closed": return "已完成"
    case "blocked": return "等待处理"
    case "failed": return "失败"
    default: return "状态未知"
    }
}
