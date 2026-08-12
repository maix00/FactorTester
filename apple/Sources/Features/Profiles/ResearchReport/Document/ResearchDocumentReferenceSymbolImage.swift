import Foundation

#if os(macOS)
import AppKit

enum ResearchDocumentReferenceSymbolImage {
    private static let cache = NSCache<NSString, NSData>()

    static func pngData(for kind: String) -> Data? {
        if let cached = cache.object(forKey: kind as NSString) {
            return cached as Data
        }
        let symbol = ResearchDocumentReferenceCatalog.descriptor(for: kind).symbol
        guard let source = NSImage(
            systemSymbolName: symbol,
            accessibilityDescription: nil
        )?.withSymbolConfiguration(
            NSImage.SymbolConfiguration(pointSize: 13, weight: .regular)
        ) else {
            return nil
        }
        let pixelSize = NSSize(width: 28, height: 28)
        guard let bitmap = NSBitmapImageRep(
            bitmapDataPlanes: nil,
            pixelsWide: Int(pixelSize.width),
            pixelsHigh: Int(pixelSize.height),
            bitsPerSample: 8,
            samplesPerPixel: 4,
            hasAlpha: true,
            isPlanar: false,
            colorSpaceName: .deviceRGB,
            bytesPerRow: 0,
            bitsPerPixel: 0
        ) else {
            return nil
        }
        bitmap.size = pixelSize
        NSGraphicsContext.saveGraphicsState()
        defer { NSGraphicsContext.restoreGraphicsState() }
        let context = NSGraphicsContext(bitmapImageRep: bitmap)
        context?.imageInterpolation = .high
        NSGraphicsContext.current = context
        NSColor.clear.setFill()
        NSRect(origin: .zero, size: pixelSize).fill()
        source.draw(
            in: fittedRect(for: source.size, canvas: pixelSize),
            from: .zero,
            operation: .sourceOver,
            fraction: 1
        )
        guard let data = bitmap.representation(
            using: .png,
            properties: [:]
        ) else { return nil }
        cache.setObject(data as NSData, forKey: kind as NSString)
        return data
    }

    static func dataURL(for kind: String) -> String? {
        pngData(for: kind).map {
            "data:image/png;base64,\($0.base64EncodedString())"
        }
    }

    private static func fittedRect(
        for source: NSSize,
        canvas: NSSize
    ) -> NSRect {
        let maximum = NSSize(width: 24, height: 24)
        let scale = min(
            maximum.width / max(source.width, 1),
            maximum.height / max(source.height, 1)
        )
        let size = NSSize(
            width: source.width * scale,
            height: source.height * scale
        )
        return NSRect(
            x: (canvas.width - size.width) / 2,
            y: (canvas.height - size.height) / 2,
            width: size.width,
            height: size.height
        )
    }
}
#endif
