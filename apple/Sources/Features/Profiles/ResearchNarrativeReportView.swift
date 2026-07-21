import SwiftUI

struct ResearchNarrativeReportView: View {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let steps: [ResearchTransitionStep]
    let nextCursor: String?
    let profileName: String
    let reportTitle: String
    let artifact: ResearchArtifactModel?
    let loadEarlier: () async -> Void

    @State private var sections: [ResearchJournalSection] = []
    @State private var reportError: String?
    @State private var selectedCheckpointRef = ""
    @State private var selectedAudit: ResearchAuditSelection?

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
            .frame(width: 208)
            Divider()
            report
        }
        .popover(item: $selectedAudit) { selection in
            ResearchAuditPopover(
                selection: selection,
                detail: detail,
                steps: steps
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
            Text(section.body)
                .font(.body)
                .lineSpacing(6)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)

            if !section.links.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 7) {
                        ForEach(section.links) { link in
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
            reportError = "该历史记录没有经过校验的中文 journal；不会用摘要卡片冒充完整报告。"
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
            if selectedCheckpointRef.isEmpty {
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

    private func selectCheckpoint(_ checkpointRef: String) {
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

    private var step: ResearchTransitionStep? {
        steps.first { $0.stepRef == selection.checkpointRef }
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
                if selection.link.kind == "obligation",
                   let obligation = detail.researchCycle.obligations.first(where: {
                       $0.obligationRef == selection.link.targetRef
                   }) {
                    Text(obligation.questionSummary)
                        .font(.callout)
                    Text("当前义务状态：\(obligation.status)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } else {
                Text("完整对象详情将在用户明确展开时按引用读取；正文不会预载整份审计历史。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(18)
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
