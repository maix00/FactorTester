#if os(macOS)
import AppKit
import CoreText

struct ResearchReportPDFRenderer: ResearchReportRenderer {
    private let pageSize = CGSize(width: 595, height: 842)
    private let margin: CGFloat = 54

    func render(_ source: ResearchReportExportSource) throws -> Data {
        let markdown = String(
            decoding: try source.markdownData(),
            as: UTF8.self
        )
        let attributed = attributedMarkdown(markdown)
        let output = NSMutableData()
        guard let consumer = CGDataConsumer(data: output as CFMutableData) else {
            throw ResearchReportExportError.pdfContextUnavailable
        }
        var mediaBox = CGRect(origin: .zero, size: pageSize)
        guard let context = CGContext(
            consumer: consumer,
            mediaBox: &mediaBox,
            nil
        ) else {
            throw ResearchReportExportError.pdfContextUnavailable
        }
        draw(attributed, in: context)
        context.closePDF()
        return output as Data
    }

    private func attributedMarkdown(_ markdown: String) -> NSAttributedString {
        let value = (try? AttributedString(
            markdown: markdown,
            options: .init(interpretedSyntax: .full)
        )) ?? AttributedString(markdown)
        let output = NSMutableAttributedString(attributedString: .init(value))
        output.addAttribute(
            .foregroundColor,
            value: NSColor.textColor,
            range: NSRange(location: 0, length: output.length)
        )
        return output
    }

    private func draw(
        _ attributed: NSAttributedString,
        in context: CGContext
    ) {
        let framesetter = CTFramesetterCreateWithAttributedString(attributed)
        let textRect = CGRect(
            x: margin,
            y: margin,
            width: pageSize.width - margin * 2,
            height: pageSize.height - margin * 2
        )
        var offset = 0
        repeat {
            context.beginPDFPage(nil)
            context.saveGState()
            context.translateBy(x: 0, y: pageSize.height)
            context.scaleBy(x: 1, y: -1)
            let path = CGPath(rect: textRect, transform: nil)
            let frame = CTFramesetterCreateFrame(
                framesetter,
                CFRange(location: offset, length: 0),
                path,
                nil
            )
            CTFrameDraw(frame, context)
            let visible = CTFrameGetVisibleStringRange(frame)
            offset += visible.length
            context.restoreGState()
            context.endPDFPage()
            if visible.length == 0 { break }
        } while offset < attributed.length
    }
}
#endif
