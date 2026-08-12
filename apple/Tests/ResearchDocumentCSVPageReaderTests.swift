import XCTest
@testable import FTClient

final class ResearchDocumentCSVPageReaderTests: XCTestCase {
    func testReadsQuotedCellsAndEmbeddedLineBreaks() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString + ".csv")
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        let csv = """
        metric,value
        IC,0.03
        note,"line one
        line two, quoted"
        """
        try Data(csv.utf8).write(to: url)

        let reader = try ResearchDocumentCSVPageReader(url: url)

        XCTAssertEqual(try reader.nextRow(), ["metric", "value"])
        XCTAssertEqual(try reader.nextRow(), ["IC", "0.03"])
        XCTAssertEqual(
            try reader.nextRow(),
            ["note", "line one\nline two, quoted"]
        )
        XCTAssertNil(try reader.nextRow())
    }
}
