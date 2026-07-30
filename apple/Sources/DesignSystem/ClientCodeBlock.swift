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
            alignedScrollView
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private var alignedScrollView: some View {
        if #available(macOS 14.0, iOS 17.0, *) {
            codeScrollView.defaultScrollAnchor(.topLeading)
        } else {
            codeScrollView
        }
    }

    private var codeScrollView: some View {
        ScrollView([.horizontal, .vertical]) {
            HStack(spacing: 0) {
                Text(verbatim: source)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .multilineTextAlignment(.leading)
                    .lineSpacing(4)
                    .fixedSize(horizontal: true, vertical: false)
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
        }
        .frame(maxWidth: .infinity, maxHeight: maximumHeight, alignment: .topLeading)
        .background(
            Color.black.opacity(0.045),
            in: RoundedRectangle(cornerRadius: 7)
        )
    }
}
