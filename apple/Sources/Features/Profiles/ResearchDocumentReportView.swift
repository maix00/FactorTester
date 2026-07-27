import Foundation
import SwiftUI

private struct LocalReportComponent: Identifiable {
    let id: String
    let kind: String
    let parentID: String?
    let title: String
    let body: String
    let content: String
}

struct ResearchDocumentReportView: View {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let profileName: String
    let reportTitle: String
    let artifact: ResearchArtifactModel

    @State private var title = ""
    @State private var components: [LocalReportComponent] = []
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                if let error {
                    Label(error, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.secondary)
                } else if components.isEmpty {
                    ProgressView(L10n.text("正在读取本地研究报告…"))
                } else {
                    ForEach(components.filter { $0.kind == "chapter" }) {
                        chapter in
                        chapterView(chapter)
                    }
                }
            }
            .frame(maxWidth: 820, alignment: .leading)
            .padding(.horizontal, 42)
            .padding(.vertical, 34)
            .frame(maxWidth: .infinity, alignment: .center)
        }
        .task(id: artifact.localRef) { await load() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.isEmpty ? reportTitle : title)
                .font(.largeTitle.weight(.bold))
            Text(L10n.format("由 %@ 负责 · 当前阶段：%@", profileName,
                             ResearchDisplayText.node(detail.currentNode)))
                .font(.callout)
                .foregroundStyle(.secondary)
            Text(L10n.text("研究节点进入后自动建立章节，正文和证据可在本地报告中继续补充。"))
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func chapterView(_ chapter: LocalReportComponent) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(chapter.title).font(.title2.weight(.semibold))
            if !chapter.body.isEmpty { Text(chapter.body) }
            ForEach(components.filter { $0.parentID == chapter.id }) { item in
                VStack(alignment: .leading, spacing: 5) {
                    Text(item.title).font(.headline)
                    if !item.body.isEmpty { Text(item.body) }
                    if !item.content.isEmpty {
                        Text(item.content).font(.system(.body, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.leading, 14)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.secondary.opacity(0.045),
                    in: RoundedRectangle(cornerRadius: 14))
    }

    private func load() async {
        guard let url = URL(string: artifact.localRef), url.isFileURL else {
            error = L10n.text("本地报告路径无效")
            return
        }
        do {
            let (loadedTitle, loadedComponents) = try await Task.detached {
                let data = try PersonalWorkspaceAccessStore.withAccess(to: url) {
                    try Data(contentsOf: url)
                }
                guard let root = try JSONSerialization.jsonObject(
                    with: data
                ) as? [String: Any] else { throw ReportDocumentError.invalid }
                let values = (root["components"] as? [[String: Any]] ?? []).compactMap {
                    Self.component($0)
                }
                return (root["title"] as? String ?? "", values)
            }.value
            title = loadedTitle
            components = loadedComponents
            error = nil
        } catch {
            self.error = L10n.text("本地研究报告无法读取")
        }
    }

    private static func component(
        _ value: [String: Any]
    ) -> LocalReportComponent? {
        guard let id = value["component_id"] as? String,
              let kind = value["kind"] as? String,
              let title = value["title"] as? String else { return nil }
        var content = ""
        if let object = value["content"] {
            if let dict = object as? [String: Any], let code = dict["code"] as? String {
                content = code
            } else if let dict = object as? [String: Any], let latex = dict["latex"] as? String {
                content = latex
            } else if JSONSerialization.isValidJSONObject(object),
                      let data = try? JSONSerialization.data(withJSONObject: object),
                      let text = String(data: data, encoding: .utf8) {
                content = text
            }
        }
        return LocalReportComponent(
            id: id, kind: kind, parentID: value["parent_id"] as? String,
            title: title, body: value["body"] as? String ?? "", content: content
        )
    }
}

private enum ReportDocumentError: Error { case invalid }
