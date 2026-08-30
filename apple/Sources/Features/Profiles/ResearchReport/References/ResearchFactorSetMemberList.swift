import SwiftUI

struct ResearchFactorSetMemberList: View {
    let targetRef: String

    @State private var members: [ResearchDocumentRelatedReference] = []
    @State private var nextOffset = 0
    @State private var hasMore = true
    @State private var isLoading = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text(L10n.text("集合成员"))
                .font(.subheadline.weight(.semibold))
            ResearchDocumentRelatedReferenceList(links: members)
            if isLoading {
                ProgressView(L10n.text("正在读取集合成员…"))
                    .controlSize(.small)
            } else if let error {
                Label(error, systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else if hasMore {
                Button(L10n.text("加载更多")) {
                    Task { await loadNextPage() }
                }
                .buttonStyle(.borderless)
            }
        }
        .task(id: targetRef) {
            members = []
            nextOffset = 0
            hasMore = true
            await loadNextPage()
        }
    }

    @MainActor
    private func loadNextPage() async {
        guard hasMore, !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            #if os(macOS)
            try await BundledRuntimeActivator.waitUntilReady()
            let offset = nextOffset
            let value = try await ResearchFactorSetMemberPageCache.shared.value(
                targetRef: targetRef, offset: offset, limit: 50
            ) {
                try await ReleaseCommand.runObject(
                    Self.commandArguments(
                        targetRef: targetRef, offset: offset, limit: 50
                    ),
                    executable: ClientCLIResolution.executable()
                )
            }
            let page = ResearchDocumentRelatedReferences.parse(
                value, componentID: "factor-set-members"
            )
            let known = Set(members.map(\.id))
            members.append(contentsOf: page.filter { !known.contains($0.id) })
            nextOffset = value["next_offset"] as? Int ?? members.count
            hasMore = value["has_more"] as? Bool ?? false
            error = nil
            #endif
        } catch {
            self.error = error.localizedDescription
        }
    }

    static func commandArguments(
        targetRef: String,
        offset: Int,
        limit: Int
    ) -> [String] {
        [
            "factor-library", "profile", "factor-set",
            "members", "--target-ref", targetRef,
            "--offset", String(offset), "--limit", String(limit), "--json",
        ]
    }
}
