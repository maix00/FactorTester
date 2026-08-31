import SwiftUI
#if os(macOS)
import AppKit
#endif

struct ResearchDocumentEvidenceFragmentList: View {
    let detail: ResearchEvidenceDetailPayload
    let canDownload: Bool
    let reportRef: String
    let openJob: (String, Int?, String) -> Void

    var body: some View {
        if !detail.fragments.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Text(L10n.text("来源片段"))
                    .font(.subheadline.weight(.semibold))
                ForEach(detail.fragments) { fragment in
                    fragmentRow(fragment)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        if !detail.tags.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text(L10n.text("Agent 标签"))
                    .font(.subheadline.weight(.semibold))
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(detail.tags) { tag in
                            Text(tag.titleZH)
                                .font(.caption)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(.secondary.opacity(0.1))
                                .clipShape(Capsule())
                                .help(tag.descriptionZH)
                        }
                    }
                }
            }
        }
    }

    private func fragmentRow(
        _ fragment: ResearchEvidenceFragment
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: symbol(fragment.source.sourceKind))
                    .foregroundStyle(.secondary)
                Text(fragment.titleZH)
                    .font(.callout.weight(.medium))
                Spacer()
                sourceAction(fragment)
            }
            Text(fragment.summaryZH)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(fragment.preview.scalarText ?? L10n.text("结构化片段"))
                .font(.caption.monospaced())
                .textSelection(.enabled)
                .lineLimit(6)
        }
        .padding(10)
        .background(.secondary.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    @ViewBuilder
    private func sourceAction(
        _ fragment: ResearchEvidenceFragment
    ) -> some View {
        let identity = fragment.source.identity.objectValue
        switch fragment.source.sourceKind {
        case "job":
            if let jobID = identity["job_id"]?.scalarText {
                Button(L10n.text("打开测试任务")) {
                    let port = identity["service_port"]?.scalarText.flatMap {
                        Int($0)
                    }
                    let serverID = identity["server_id"]?.scalarText ?? ""
                    openJob(jobID, port, serverID)
                }
                .buttonStyle(.link)
            }
        case "file":
            if canDownload,
               identity["object_id"]?.scalarText != nil,
               identity["storage_server_id"]?.scalarText != nil {
                Button(L10n.text("下载文件")) {
                    Task { await downloadFile(fragment) }
                }
                .buttonStyle(.link)
            } else if let relative = identity["relative_path"]?.scalarText,
               let url = localFileURL(relative) {
                Button(L10n.text("打开文件")) {
                    #if os(macOS)
                    _ = try? PersonalWorkspaceAccessStore.withAccess(to: url) {
                        ResearchDocumentExternalURLLauncher.open(url)
                    }
                    #endif
                }
                .buttonStyle(.link)
            }
        case "web":
            if let raw = identity["url"]?.scalarText,
               let url = URL(string: raw),
               ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
                Button(L10n.text("打开网页")) {
                    #if os(macOS)
                    ResearchDocumentExternalURLLauncher.open(url)
                    #endif
                }
                .buttonStyle(.link)
            }
        default:
            EmptyView()
        }
    }

    @MainActor
    private func downloadFile(_ fragment: ResearchEvidenceFragment) async {
        #if os(macOS)
        do {
            let value = try await ManagerObjectTransferService.shared.downloadEvidenceFile(
                evidenceRef: detail.evidenceRef,
                sourceRef: fragment.sourceRef
            )
            let panel = NSSavePanel()
            panel.nameFieldStringValue = value.filename
            guard panel.runModal() == .OK, let destination = panel.url else { return }
            try value.data.write(to: destination, options: .atomic)
        } catch {
            NSSound.beep()
        }
        #endif
    }

    private func localFileURL(_ relative: String) -> URL? {
        guard ResearchDocumentTypedLinkParser.isSafeRelativeFilePath(relative),
              let reportURL = URL(string: reportRef),
              reportURL.isFileURL else { return nil }
        var cursor = reportURL.deletingLastPathComponent()
        while cursor.path != "/" {
            if cursor.deletingLastPathComponent().lastPathComponent == "users" {
                return relative.split(separator: "/").reduce(cursor) {
                    $0.appendingPathComponent(String($1), isDirectory: false)
                }.standardizedFileURL
            }
            cursor = cursor.deletingLastPathComponent()
        }
        return nil
    }

    private func symbol(_ sourceKind: String) -> String {
        switch sourceKind {
        case "job": return "checklist"
        case "terminal": return "terminal"
        case "file": return "doc"
        case "web": return "globe"
        default: return "scope"
        }
    }
}

private extension ResearchJSONValue {
    var objectValue: [String: ResearchJSONValue] {
        if case let .object(value) = self { return value }
        return [:]
    }
}
