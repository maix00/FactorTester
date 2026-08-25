import SwiftUI

struct ResearchDocumentReferenceOverlay: View {
    let reference: ResearchDocumentTypedLink
    let binding: ResearchDocumentBinding?
    let asset: ResearchDocumentAsset?
    let reportRef: String
    let serverURL: URL
    let objectHref: String?
    let openJobSource: (String, Int?, String) -> Void
    var showsDismiss = true

    @Environment(\.dismiss) private var dismiss
    @State private var payload: ResearchAuditObjectPayload?
    @State private var evidenceDetail: ResearchEvidenceDetailPayload?
    @State private var registryObjectJSON: String?
    @State private var isLoading = false
    @State private var error: String?

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    if let asset {
                        ResearchDocumentAssetView(
                            asset: asset,
                            reportRef: reportRef
                        )
                    }
                    detailSections
                    if reference.kind == "factor",
                       reference.targetRef.hasPrefix("factor-set:v2:") {
                        ResearchFactorSetMemberList(
                            targetRef: reference.targetRef
                        )
                    }
                    if let evidenceDetail {
                        ResearchDocumentEvidenceFragmentList(
                            detail: evidenceDetail,
                            reportRef: reportRef,
                            openJob: openJobSource
                        )
                    }
                    frozenObjectJSON
                    if isLoading {
                        ProgressView(L10n.text("正在读取对象详情…"))
                    } else if let error {
                        Label(error, systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(20)
            }
        }
        .frame(minWidth: 520, idealWidth: 620, minHeight: 340, idealHeight: 560)
        .task(id: reference.id) { await load() }
    }

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: ResearchDocumentTypedLinkPresentation.symbol(
                for: reference.kind
            ))
                .foregroundStyle(
                    ResearchDocumentTypedLinkPresentation.color(
                        for: reference.kind
                    )
                )
            VStack(alignment: .leading, spacing: 2) {
                Text(reference.label).font(.headline)
                Text(ResearchDocumentTypedLinkPresentation.title(
                    for: reference.kind
                ))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if showsDismiss {
                Button(L10n.text("完成")) { dismiss() }
                    .keyboardShortcut(.cancelAction)
            }
        }
        .padding(16)
    }

    private var detailSections: some View {
        ForEach(ResearchDocumentReferenceDetails.sections(
                reference: reference,
                binding: binding,
                payload: payload,
                evidence: evidenceDetail
            )) { section in
                ResearchDocumentReferenceSectionView(section: section)
        }
    }

    @ViewBuilder
    private var frozenObjectJSON: some View {
        if let json = ResearchFrozenObjectJSON.resolve(
            kind: reference.kind,
            payload: payload,
            registryJSON: registryObjectJSON
        ) {
            ResearchRunSpecConfigurationView(
                objectKind: reference.kind,
                phase: .frozen,
                configurationJSON: json
            )
        }
    }

    @MainActor
    private func load() async {
        guard objectHref != nil
                || reference.kind == "evidence"
                || ResearchFrozenObjectJSON.supports(reference.kind) else {
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            let service = ProfileResearchService.unified(serviceURL: serverURL)
            if let objectHref {
                payload = try await service.auditObject(href: objectHref)
                if reference.kind == "evidence" {
                    evidenceDetail = try? await service.evidence(
                        reference: reference.targetRef
                    )
                }
            } else {
                if reference.kind == "evidence" {
                    evidenceDetail = try await service.evidence(
                        reference: reference.targetRef
                    )
                } else {
                    registryObjectJSON = try await service.frozenObjectJSON(
                        reference: reference
                    )
                }
            }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

enum ResearchFrozenObjectJSON {
    static func supports(_ kind: String) -> Bool {
        ["trial_plan", "run_spec", "run"].contains(kind)
    }

    static func resolve(
        kind: String,
        payload: ResearchAuditObjectPayload?,
        registryJSON: String?
    ) -> String? {
        let value: String?
        switch kind {
        case "trial_plan", "run_spec":
            value = registryJSON ?? payload?.completeParametersJSON
        case "run":
            value = registryJSON ?? payload?.runSpecJSON
        default:
            value = nil
        }
        guard let value, !value.isEmpty else { return nil }
        return value
    }
}
