import SwiftUI

struct WorkPackageResearchView: View {
    @EnvironmentObject private var session: SessionStore
    let item: ResearchDirectoryItem
    let profiles: [LocalProfileModel]
    let primaryProfile: LocalProfileModel
    let isActive: Bool
    @ObservedObject var tabSession: ClientTabSession
    let openJob: (TestJob) -> Void
    let openProfile: (String, String) -> Void
    let openReferencePage: (ResearchDocumentTypedLink) -> Void
    let onCheckpointChange: @MainActor (String) -> Void

    @StateObject private var controller: ProfileLiveProcessController
    @State private var branchTask: Task<Void, Never>?
    @State private var exportError: String?
    @State private var gateStatus: ResearchHumanGateOverrideStatus?
    @State private var requestedGateValue = false
    @State private var isGateAuthorizationPresented = false
    @State private var gateError: String?

    init(
        item: ResearchDirectoryItem,
        profiles: [LocalProfileModel],
        primaryProfile: LocalProfileModel,
        isActive: Bool,
        tabSession: ClientTabSession,
        openJob: @escaping (TestJob) -> Void,
        openProfile: @escaping (String, String) -> Void,
        openReferencePage: @escaping (ResearchDocumentTypedLink) -> Void,
        onCheckpointChange: @escaping @MainActor (String) -> Void
    ) {
        self.item = item
        self.profiles = profiles
        self.primaryProfile = primaryProfile
        self.isActive = isActive
        self.tabSession = tabSession
        self.openJob = openJob
        self.openProfile = openProfile
        self.openReferencePage = openReferencePage
        self.onCheckpointChange = onCheckpointChange
        _controller = StateObject(
            wrappedValue: ProfileLiveProcessController(
                profile: primaryProfile,
                pinnedSummary: item.summary,
                initialWorkspaceID: item.workspaceID,
                initialBranchID: tabSession.selectedBranchID,
                onCheckpointChange: onCheckpointChange
            )
        )
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ProfileLiveResearchDetail(
                profiles: profiles,
                controller: controller,
                tabSession: tabSession,
                serverURL: item.serverURL,
                openJob: openJob,
                openProfile: openProfile,
                openReferencePage: openReferencePage
            )
        }
        .task(id: "\(isActive)|\(item.id)") {
            guard isActive else { return }
            await controller.observeSelectedResearch()
        }
        .onChange(of: controller.selectedBranchID) { branchID in
            tabSession.selectedBranchID = branchID
            guard isActive, controller.detail != nil else { return }
            branchTask?.cancel()
            branchTask = Task { await controller.observeSelectedResearch() }
        }
        .onChange(of: isActive) { active in
            if !active {
                branchTask?.cancel()
                branchTask = nil
            }
        }
        .onDisappear {
            tabSession.selectedBranchID = controller.selectedBranchID
            branchTask?.cancel()
            branchTask = nil
        }
        .alert(
            L10n.text("研究报告导出失败"),
            isPresented: Binding(
                get: { exportError != nil },
                set: { if !$0 { exportError = nil } }
            )
        ) {
            Button(L10n.text("好"), role: .cancel) {}
        } message: {
            Text(exportError ?? "")
        }
        .task(id: gateScopeKey) {
            await loadGateStatus()
        }
        .sheet(isPresented: $isGateAuthorizationPresented) {
            gateAuthorizationSheet
        }
    }

    private var header: some View {
        HStack(spacing: 14) {
            Image(systemName: "point.3.connected.trianglepath.dotted")
                .font(.title2)
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 4) {
                Text(item.displayTitle)
                    .font(.title2.weight(.semibold))
                HStack(spacing: 8) {
                    Text("研究工作包")
                    Text(item.summary.workPackageRef).monospaced()
                    Text("·")
                    Text(verbatim: L10n.format(
                        "研究身份：%@",
                        item.profileNames.joined(separator: "、")
                    ))
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            }
            Spacer()
            if let workPackage = controller.workPackage {
                ResearchBranchPicker(
                    branches: workPackage.branches,
                    profiles: profiles,
                    selectedBranchID: $controller.selectedBranchID
                )
            }
            if controller.isLoading {
                ProgressView().controlSize(.small)
            }
            reportActions
        }
        .padding(18)
    }

    private var reportActions: some View {
        HStack(spacing: 10) {
            Button {
                Task { await controller.refreshSelectedResearch() }
            } label: {
                Image(systemName: "arrow.clockwise")
                    .frame(width: 30, height: 30)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(L10n.text("刷新进度"))
            .accessibilityLabel(L10n.text("刷新进度"))
            .accessibilityIdentifier("research.report.refresh")
            .disabled(controller.selectedBranch == nil)

            Menu {
                ForEach(
                    ResearchReportExportFormat.allCases,
                    id: \.self
                ) { format in
                    Button(format.localizedTitle) {
                        exportReport(format)
                    }
                }
            } label: {
                Image(systemName: "square.and.arrow.up")
                    .frame(width: 30, height: 30)
                    .contentShape(Rectangle())
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .help(L10n.text("导出研究报告"))
            .accessibilityLabel(L10n.text("导出研究报告"))
            .accessibilityIdentifier("research.report.export")
            .disabled(controller.selectedBranch == nil)

            HStack(spacing: 7) {
                Text(L10n.text("未完全覆盖时仍允许推进"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Toggle("", isOn: Binding(
                    get: { gateStatus?.enabled == true },
                    set: { value in
                        requestedGateValue = value
                        gateError = nil
                        isGateAuthorizationPresented = true
                    }
                ))
                .labelsHidden()
                .toggleStyle(.switch)
                .controlSize(.small)
                .accessibilityLabel(L10n.text("跳过覆盖完整性门闸"))
                .accessibilityIdentifier(
                    "research.node.advance.gate.override"
                )
            }
            .help(L10n.text(
                "允许带着未完全覆盖的义务推进；未覆盖项仍会显示并提示处理"
            ))
            .disabled(controller.detail == nil || !session.isLoggedIn)
        }
        .frame(height: ResearchBranchPicker.controlHeight)
    }

    private var gateScopeKey: String {
        guard let detail = controller.detail else { return "unavailable" }
        return "\(detail.branchID)|\(detail.currentNode)|\(detail.latestTraceRef ?? "")"
    }

    private var gateAuthorizationSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(
                requestedGateValue
                    ? L10n.text("允许未完全覆盖时推进")
                    : L10n.text("恢复完整覆盖门闸"),
                systemImage: requestedGateValue
                    ? "lock.open.trianglebadge.exclamationmark"
                    : "lock.shield"
            )
            .font(.headline)
            Text(L10n.text(
                "该设置不会绕过报告结构、引用、身份、哈希、上下文或研究图门禁；未覆盖项仍会写入覆盖表并提示 Research Agent 处理"
            ))
            .font(.callout)
            .foregroundStyle(.secondary)
            if let gateError {
                Label(gateError, systemImage: "exclamationmark.circle.fill")
                    .font(.footnote)
                    .foregroundStyle(.red)
            }
            AccountCredentialAuthorizationView(
                fixedUsername: session.user?.username ?? "",
                submitTitle: L10n.text("确认"),
                reason: L10n.text("授权研究节点覆盖门闸设置"),
                isWorking: false,
                submit: { _, password in
                    await authorizeGate(password: password)
                },
                cancel: { isGateAuthorizationPresented = false }
            )
        }
        .padding(22)
        .frame(width: 480)
    }

    private func loadGateStatus() async {
        guard let detail = controller.detail else {
            gateStatus = nil
            return
        }
        do {
            gateStatus = try await gateService.status(
                instanceID: instanceID(detail.branchRef),
                branchID: detail.branchID
            )
        } catch {
            gateStatus = nil
        }
    }

    private func authorizeGate(password: String) async -> Bool {
        guard let detail = controller.detail else { return false }
        do {
            gateStatus = try await gateService.authorize(
                instanceID: instanceID(detail.branchRef),
                branchID: detail.branchID,
                expectedNode: detail.currentNode,
                expectedCheckpointRef: detail.latestTraceRef ?? "",
                enabled: requestedGateValue,
                password: password
            )
            isGateAuthorizationPresented = false
            return true
        } catch {
            gateError = error.localizedDescription
            return false
        }
    }

    private var gateService: ResearchHumanGateOverrideService {
        ResearchHumanGateOverrideService(baseURL: item.serverURL)
    }

    private func instanceID(_ branchRef: String) -> String {
        let parts = branchRef.split(separator: ":", omittingEmptySubsequences: false)
        return parts.count == 3 ? String(parts[1]) : ""
    }

    private func exportReport(_ format: ResearchReportExportFormat) {
        guard let branch = controller.selectedBranch else { return }
        Task { @MainActor in
            do {
                try await ResearchReportExportController.export(
                    format: format,
                    profileID: primaryProfile.id,
                    workPackageID: referenceID(
                        controller.workPackage?.workPackageRef
                            ?? item.summary.workPackageRef,
                        prefix: "work-package:"
                    ),
                    branchID: branch.branchID,
                    title: item.displayTitle
                )
            } catch {
                exportError = error.localizedDescription
            }
        }
    }

    private func referenceID(_ value: String, prefix: String) -> String {
        value.hasPrefix(prefix) ? String(value.dropFirst(prefix.count)) : value
    }
}
