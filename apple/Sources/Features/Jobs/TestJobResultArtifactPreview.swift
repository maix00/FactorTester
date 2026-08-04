import SwiftUI

enum TestJobResultArtifactResolver {
    static func image(
        for declaration: TestJobOutputDeclaration,
        in artifacts: [TestJobArtifact]
    ) -> TestJobArtifact? {
        guard declaration.presentation == "chart",
              !["price_chart", "kline_volume", "order_flow"].contains(
                declaration.viewer
              ) else { return nil }
        return candidates(for: declaration, in: artifacts)
            .filter { $0.contentType.hasPrefix("image/") }
            .sorted { imagePriority($0) < imagePriority($1) }
            .first
    }

    static func table(
        for declaration: TestJobOutputDeclaration,
        in artifacts: [TestJobArtifact]
    ) -> TestJobArtifact? {
        guard declaration.presentation == "table"
                || declaration.viewer == "data_table" else { return nil }
        let dataArtifactName = "\(declaration.name)_data"
        return candidates(for: declaration, in: artifacts).first {
            $0.name == dataArtifactName
                && $0.contentType.hasPrefix("application/json")
        }
    }

    private static func candidates(
        for declaration: TestJobOutputDeclaration,
        in artifacts: [TestJobArtifact]
    ) -> [TestJobArtifact] {
        let declaredNames = Set(declaration.artifacts)
        let fallbackNames: Set<String> = [
            "\(declaration.name)_report", "\(declaration.name)_data",
        ]
        let names = declaredNames.isEmpty ? fallbackNames : declaredNames
        return artifacts.filter { $0.state == "active" && names.contains($0.name) }
    }

    private static func imagePriority(_ artifact: TestJobArtifact) -> Int {
        artifact.contentType == "image/svg+xml" ? 0 : 1
    }
}

struct TestJobArtifactImagePreview: View {
    let artifact: TestJobArtifact
    let load: () async throws -> Data

    @State private var svgData: Data?
    @State private var rasterImage: CGImage?
    @State private var error: String?

    var body: some View {
        Group {
            if let svgData {
                DocumentPassiveSVGWebView(data: svgData)
                    .aspectRatio(16 / 9, contentMode: .fit)
            } else if let rasterImage {
                Image(decorative: rasterImage, scale: 1)
                    .resizable()
                    .scaledToFit()
            } else if let error {
                Label(error, systemImage: "photo.badge.exclamationmark")
                    .foregroundStyle(.secondary)
            } else {
                ProgressView("正在读取图表生成物…")
            }
        }
        .frame(maxWidth: .infinity, minHeight: 160, maxHeight: 520)
        .background(Color.secondary.opacity(0.045), in: RoundedRectangle(cornerRadius: 8))
        .task(id: artifact.id) { await loadArtifact() }
    }

    @MainActor
    private func loadArtifact() async {
        guard svgData == nil, rasterImage == nil else { return }
        do {
            let data = try await load()
            if artifact.contentType == "image/svg+xml" {
                try ResearchDocumentAssetLoader.validateSVG(data)
                svgData = data
            } else {
                rasterImage = try await ResearchDocumentRasterImageDecoder.decode(data)
            }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
