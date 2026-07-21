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
    let loadAuditObject: (String) async throws -> ResearchAuditObjectPayload

    @State private var sections: [ResearchJournalSection] = []
    @State private var reportError: String?
    @State private var selectedCheckpointRef = ""
    @State private var selectedAudit: ResearchAuditSelection?
    @StateObject private var auditCache = ResearchAuditObjectCache()

    var body: some View {
        HStack(spacing: 0) {
            ResearchVersionTreePane(
                detail: detail,
                workPackage: workPackage,
                steps: orderedSteps,
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
            .frame(width: 380)
        }
        .task(id: artifact?.journalHash ?? "") {
            await loadReport()
        }
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
                        ForEach(sections) { section in
                            narrativeSection(section)
                                .id(section.id)
                        }
                    }
                }
                .frame(maxWidth: 820, alignment: .leading)
                .padding(.horizontal, 42)
                .padding(.bottom, 56)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .onChange(of: selectedCheckpointRef) { checkpointRef in
                guard let section = sections.first(where: {
                    $0.checkpointRef == checkpointRef
                }) else { return }
                withAnimation(.easeInOut(duration: 0.22)) {
                    proxy.scrollTo(section.id, anchor: .top)
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
        _ section: ResearchJournalSection
    ) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Text(Date(timeIntervalSince1970: section.createdAt), style: .date)
                Text("·")
                Text(shortReference(section.checkpointRef))
                    .monospaced()
            }
            .font(.caption)
            .foregroundStyle(.tertiary)

            Text(section.title)
                .font(.title2.weight(.semibold))
                .foregroundStyle(.primary)
            if !section.body.isEmpty {
                reportParagraph(section.body, linkIDs: [], section: section)
            }
            if !section.blocks.isEmpty {
                ForEach(Array(section.blocks.enumerated()), id: \.offset) {
                    _, block in
                    reportBlock(block, section: section)
                }
            }

            if !unboundLinks(in: section).isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 7) {
                        ForEach(unboundLinks(in: section)) { link in
                            auditChip(link, checkpointRef: section.checkpointRef)
                        }
                    }
                    .padding(.vertical, 2)
                }
            }
            Divider().padding(.top, 18)
        }
        .padding(.bottom, 24)
        .contentShape(Rectangle())
        .onTapGesture {
            selectedCheckpointRef = section.checkpointRef
        }
        .accessibilityIdentifier("research.report.section.\(section.sectionID)")
    }

    private func reportParagraph(
        _ text: String,
        linkIDs: [String],
        section: ResearchJournalSection
    ) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(text)
                .font(.body)
                .lineSpacing(6)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
            if !linkIDs.isEmpty {
                HStack(spacing: 6) {
                    ForEach(section.links.filter { linkIDs.contains($0.linkID) }) {
                        link in
                        auditChip(link, checkpointRef: section.checkpointRef)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func reportBlock(
        _ block: ResearchJournalBlock,
        section: ResearchJournalSection
    ) -> some View {
        switch block.kind {
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
                            Text(row.text ?? "")
                                .lineSpacing(4)
                                .textSelection(.enabled)
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
                auditChip(link, checkpointRef: section.checkpointRef)
            }
        }
    }

    private func links(
        for row: ResearchJournalRow,
        in section: ResearchJournalSection
    ) -> [ResearchJournalLink] {
        let ids = Set(row.linkIDs)
        return section.links.filter { ids.contains($0.linkID) }
    }

    private func unboundLinks(
        in section: ResearchJournalSection
    ) -> [ResearchJournalLink] {
        let bound = Set(
            section.blocks.flatMap { block in
                block.linkIDs + block.rows.flatMap(\.linkIDs)
            }
        )
        return section.links.filter { !bound.contains($0.linkID) }
    }

    private func auditChip(
        _ link: ResearchJournalLink,
        checkpointRef: String
    ) -> some View {
        Button {
            selectedAudit = ResearchAuditSelection(
                link: link,
                checkpointRef: checkpointRef
            )
        } label: {
            Label(chipLabel(link), systemImage: chipIcon(link.kind))
                .font(.caption.weight(.medium))
                .lineLimit(1)
        }
        .buttonStyle(.bordered)
        .controlSize(.mini)
        .accessibilityIdentifier(
            "research.report.chip.\(link.kind).\(link.linkID)"
        )
    }

    private func loadReport() async {
        guard let artifact, !artifact.journalRef.isEmpty else {
            sections = []
            reportError = "报告未按新协议完成，需重做：本地记录缺少 JOURNAL.json，没有经过校验的中文 journal。请让对应 research Agent 从可信 root 重新提交该分支的 checkpoint；客户端不会用旧 REPORT.md 或 INDEX.json 冒充完整报告。"
            return
        }
        do {
            let document = try await ResearchJournalLoader.load(
                artifact: artifact
            )
            sections = ResearchJournalLoader.sections(in: document)
                .sorted {
                    if $0.createdAt != $1.createdAt {
                        return $0.createdAt < $1.createdAt
                    }
                    return $0.id < $1.id
                }
            reportError = nil
            if selectedCheckpointRef.isEmpty
                || !sections.contains(where: {
                    $0.checkpointRef == selectedCheckpointRef
                }) {
                selectedCheckpointRef = sections.last?.checkpointRef ?? ""
            }
        } catch {
            sections = []
            reportError = error.localizedDescription
        }
    }

    private var orderedSteps: [ResearchTransitionStep] {
        steps.sorted {
            if $0.createdAt != $1.createdAt { return $0.createdAt < $1.createdAt }
            return $0.id < $1.id
        }
    }

    private func selectCheckpoint(_ checkpointRef: String, _ branchID: String) {
        if branchID != detail.branchRef {
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

private struct ResearchAuditSelection: Identifiable {
    let link: ResearchJournalLink
    let checkpointRef: String
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
        VStack(alignment: .leading, spacing: 14) {
            Label(
                ResearchDisplayText.linkKind(selection.link.kind),
                systemImage: chipIcon(selection.link.kind)
            )
            .font(.headline)
            LabeledContent("稳定引用") {
                Text(selection.link.targetRef)
                    .font(.caption.monospaced())
                    .textSelection(.enabled)
            }
            LabeledContent("对应检查点") {
                Text(selection.checkpointRef)
                    .font(.caption.monospaced())
                    .textSelection(.enabled)
            }
            if let step {
                Divider()
                LabeledContent("状态转移", value: "\(step.fromNode) → \(step.toNode)")
                LabeledContent("图边", value: step.edgeRef)
                objectDetail
            } else {
                Text("该报告段落没有可验证的检查点，无法读取历史审计对象。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(18)
        .task(id: selection.id) {
            await loadSelectedObject()
        }
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
            Text("该类对象暂未提供检查点级详情；正文不会预载完整对象或审计历史。")
                .font(.caption)
                .foregroundStyle(.secondary)
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

private func chipLabel(_ link: ResearchJournalLink) -> String {
    "\(ResearchDisplayText.linkKind(link.kind)) · \(shortReference(link.targetRef))"
}

enum ResearchDisplayText {
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
