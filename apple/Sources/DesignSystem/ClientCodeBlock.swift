import SwiftUI

/// Shared source renderer for report prose and job-detail JSON/code previews.
/// The caller chooses the bounded viewport suited to its surrounding surface.
struct ClientCodeBlock: View {
    let source: String
    let language: String
    var maximumHeight: CGFloat = 260

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            if !language.isEmpty {
                Text(verbatim: language)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            ScrollView([.horizontal, .vertical]) {
                Text(verbatim: source)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
            }
            .frame(maxHeight: maximumHeight)
            .background(Color.black.opacity(0.045), in: RoundedRectangle(cornerRadius: 7))
        }
    }
}
