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
    private let bodySize: CGFloat = 12

    func render(markdown: String) throws -> Data {
        let value = (try? AttributedString(
            markdown: markdown,
            options: .init(interpretedSyntax: .full)
        )) ?? AttributedString(markdown)
        let attributed = NSMutableAttributedString(
            attributedString: NSAttributedString(value)
        )
        style(attributed, from: value)
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

    /// Markdown parsing leaves the runs without a font, so CoreText falls back
    /// to a Latin-only default and CJK text renders as garbage boxes.  Assign
    /// an explicit font whose cascade covers CJK (the system font), then add
    /// basic Markdown typography (headings, bold, italic, inline code).
    private func style(
        _ attributed: NSMutableAttributedString,
        from value: AttributedString
    ) {
        let characters = value.characters
        let full = NSRange(location: 0, length: attributed.length)
        attributed.addAttribute(
            .font,
            value: NSFont.systemFont(ofSize: bodySize, weight: .regular),
            range: full
        )
        attributed.addAttribute(
            .foregroundColor,
            value: NSColor.textColor,
            range: full
        )
        for run in value.runs {
            let start = characters.distance(
                from: characters.startIndex,
                to: run.range.lowerBound
            )
            let length = characters.distance(
                from: run.range.lowerBound,
                to: run.range.upperBound
            )
            guard length > 0 else { continue }
            let range = NSRange(location: start, length: length)
            var size = bodySize
            var weight: NSFont.Weight = .regular
            var monospaced = false
            var italic = false
            if let intent = run.presentationIntent {
                for component in intent.components {
                    switch component.kind {
                    case .header(let level):
                        size = Self.headerSize(level)
                        weight = .bold
                    case .codeBlock:
                        monospaced = true
                    default:
                        break
                    }
                }
            }
            if let inline = run.inlinePresentationIntent {
                if inline.contains(.stronglyEmphasized) { weight = .bold }
                if inline.contains(.emphasized) { italic = true }
                if inline.contains(.code) { monospaced = true }
            }
            attributed.addAttribute(
                .font,
                value: Self.font(
                    size: size,
                    weight: weight,
                    monospaced: monospaced,
                    italic: italic
                ),
                range: range
            )
        }
    }

    private static func headerSize(_ level: Int) -> CGFloat {
        switch level {
        case 1: return 24
        case 2: return 20
        case 3: return 17
        case 4: return 15
        default: return 13
        }
    }

    private static func font(
        size: CGFloat,
        weight: NSFont.Weight,
        monospaced: Bool,
        italic: Bool
    ) -> NSFont {
        if monospaced {
            return NSFont.monospacedSystemFont(ofSize: size, weight: weight)
        }
        let font = NSFont.systemFont(ofSize: size, weight: weight)
        if italic {
            let descriptor = font.fontDescriptor.withSymbolicTraits(
                font.fontDescriptor.symbolicTraits.union(.italic)
            )
            if let italicFont = NSFont(descriptor: descriptor, size: size) {
                return italicFont
            }
        }
        return font
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
