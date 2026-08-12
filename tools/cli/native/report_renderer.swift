#if os(macOS)
import AppKit
import CoreText
import Foundation

private enum RendererError: LocalizedError {
    case invalidArguments
    case pdfContextUnavailable

    var errorDescription: String? {
        switch self {
        case .invalidArguments:
            return "usage: factortester-report-renderer --input REPORT.md --output REPORT.pdf"
        case .pdfContextUnavailable:
            return "unable to create PDF document"
        }
    }
}

private struct ReportPDFRenderer {
    private let pageSize = CGSize(width: 595, height: 842)
    private let margin: CGFloat = 54

    func render(markdown: String) throws -> Data {
        let value = (try? AttributedString(
            markdown: markdown,
            options: .init(interpretedSyntax: .full)
        )) ?? AttributedString(markdown)
        let attributed = NSMutableAttributedString(
            attributedString: NSAttributedString(value)
        )
        attributed.addAttribute(
            .foregroundColor,
            value: NSColor.textColor,
            range: NSRange(location: 0, length: attributed.length)
        )
        let output = NSMutableData()
        guard let consumer = CGDataConsumer(data: output as CFMutableData) else {
            throw RendererError.pdfContextUnavailable
        }
        var mediaBox = CGRect(origin: .zero, size: pageSize)
        guard let context = CGContext(
            consumer: consumer,
            mediaBox: &mediaBox,
            nil
        ) else {
            throw RendererError.pdfContextUnavailable
        }
        draw(attributed, in: context)
        context.closePDF()
        return output as Data
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

private func parseArguments() throws -> (input: URL, output: URL) {
    if CommandLine.arguments.dropFirst() == ["--help"] {
        print(RendererError.invalidArguments.localizedDescription)
        exit(EXIT_SUCCESS)
    }
    var values: [String: String] = [:]
    var index = 1
    while index < CommandLine.arguments.count {
        let key = CommandLine.arguments[index]
        guard index + 1 < CommandLine.arguments.count else {
            throw RendererError.invalidArguments
        }
        values[key] = CommandLine.arguments[index + 1]
        index += 2
    }
    guard let input = values["--input"], let output = values["--output"],
          values.count == 2 else {
        throw RendererError.invalidArguments
    }
    return (
        URL(fileURLWithPath: input),
        URL(fileURLWithPath: output)
    )
}

do {
    let arguments = try parseArguments()
    let markdown = try String(contentsOf: arguments.input, encoding: .utf8)
    let data = try ReportPDFRenderer().render(markdown: markdown)
    try data.write(to: arguments.output, options: .atomic)
} catch {
    FileHandle.standardError.write(
        Data((error.localizedDescription + "\n").utf8)
    )
    exit(EXIT_FAILURE)
}
#else
fatalError("factortester-report-renderer requires macOS")
#endif
