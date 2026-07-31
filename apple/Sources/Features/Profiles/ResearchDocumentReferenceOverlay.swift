import SwiftUI

struct ResearchDocumentReferenceOverlay: View {
    let reference: ResearchDocumentTypedLink
    let binding: ResearchDocumentBinding?
    let asset: ResearchDocumentAsset?
    let reportRef: String
    let serverURL: URL
    let objectHref: String?
    let openJobSource: (String, Int) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var payload: ResearchAuditObjectPayload?
    @State private var evidenceDetail: ResearchEvidenceDetailPayload?
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
                    if let evidenceDetail {
                        ResearchDocumentEvidenceFragmentList(
                            detail: evidenceDetail,
                            reportRef: reportRef,
                            defaultPort: serverURL.port ?? 8141,
                            openJob: openJobSource
                        )
                    }
                    runSpecConfiguration
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
            Button(L10n.text("完成")) { dismiss() }
                .keyboardShortcut(.cancelAction)
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
    private var runSpecConfiguration: some View {
        if reference.kind == "run_spec",
           let json = payload?.completeParametersJSON,
           !json.isEmpty {
            ResearchRunSpecConfigurationView(
                phase: .frozen,
                configurationJSON: json
            )
        } else if reference.kind == "run",
                  let json = payload?.runSpecJSON,
                  !json.isEmpty {
            ResearchRunSpecConfigurationView(
                phase: .frozen,
                configurationJSON: json
            )
        }
    }

    @MainActor
    private func load() async {
        guard objectHref != nil || reference.kind == "evidence" else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let service = ProfileResearchService(baseURL: serverURL)
            if let objectHref {
                payload = try await service.auditObject(href: objectHref)
                if reference.kind == "evidence" {
                    evidenceDetail = try? await service.evidence(
                        reference: reference.targetRef
                    )
                }
            } else {
                evidenceDetail = try await service.evidence(
                    reference: reference.targetRef
                )
            }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
