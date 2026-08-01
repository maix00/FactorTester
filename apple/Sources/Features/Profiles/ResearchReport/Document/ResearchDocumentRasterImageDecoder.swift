import Foundation
import ImageIO

enum ResearchDocumentRasterImageDecoder {
    private static let maximumPixelSize = 2_048

    static func decode(_ data: Data) async throws -> CGImage {
        try await Task.detached(priority: .userInitiated) {
            guard let source = CGImageSourceCreateWithData(data as CFData, nil) else {
                throw ResearchDocumentRasterImageError.invalidImage
            }
            let options: [CFString: Any] = [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: maximumPixelSize,
                kCGImageSourceShouldCacheImmediately: true,
            ]
            guard let image = CGImageSourceCreateThumbnailAtIndex(
                source, 0, options as CFDictionary
            ) else {
                throw ResearchDocumentRasterImageError.invalidImage
            }
            return image
        }.value
    }
}

private enum ResearchDocumentRasterImageError: LocalizedError {
    case invalidImage

    var errorDescription: String? {
        switch self {
        case .invalidImage: return L10n.text("报告图片格式无效")
        }
    }
}
