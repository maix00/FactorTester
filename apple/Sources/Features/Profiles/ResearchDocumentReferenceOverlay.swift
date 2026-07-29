import SwiftUI

struct ResearchDocumentReferenceOverlay: View {
    let reference: ResearchDocumentTypedLink
    let binding: ResearchDocumentBinding?
    let asset: ResearchDocumentAsset?
    let reportRef: String
    let serverURL: URL
    let objectHref: String?

    @Environment(\.dismiss) private var dismiss
    @State private var payload: ResearchAuditObjectPayload?
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
                    fields
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
                .foregroundStyle(.tint)
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

    private var fields: some View {
        Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 9) {
            ForEach(ResearchDocumentReferenceDetails.fields(
                reference: reference,
                binding: binding,
                payload: payload
            )) { field in
                GridRow {
                    Text(L10n.text(field.name))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(field.value)
                        .font(.callout)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }

    @MainActor
    private func load() async {
        guard let objectHref else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            payload = try await ProfileResearchService(
                baseURL: serverURL
            ).auditObject(href: objectHref)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
