import Foundation
import XCTest
@testable import FTClient

final class LocalDocumentsRootTests: XCTestCase {
    func testNewLegacyAliasedAndConflictingRoots() throws {
        let fm = FileManager.default
        let home = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? fm.removeItem(at: home) }
        let documents = home.appendingPathComponent("Documents", isDirectory: true)
        let legacy = documents.appendingPathComponent("FactorTester", isDirectory: true)
        let current = documents.appendingPathComponent("TradeResearch", isDirectory: true)
        XCTAssertEqual(try LocalDocumentsRoot.resolve(home: home), current)
        try fm.createDirectory(at: legacy, withIntermediateDirectories: true)
        XCTAssertEqual(try LocalDocumentsRoot.resolve(home: home), legacy)
        try fm.createSymbolicLink(at: current, withDestinationURL: legacy)
        XCTAssertEqual(try LocalDocumentsRoot.resolve(home: home), current)
        try fm.removeItem(at: current)
        try fm.createDirectory(at: current, withIntermediateDirectories: true)
        XCTAssertThrowsError(try LocalDocumentsRoot.resolve(home: home))
    }

    func testBrokenLegacyAliasIsRejected() throws {
        let fm = FileManager.default
        let home = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? fm.removeItem(at: home) }
        let documents = home.appendingPathComponent("Documents", isDirectory: true)
        try fm.createDirectory(at: documents, withIntermediateDirectories: true)
        try fm.createSymbolicLink(at: documents.appendingPathComponent("FactorTester"),
                                  withDestinationURL: documents.appendingPathComponent("missing"))
        XCTAssertThrowsError(try LocalDocumentsRoot.resolve(home: home))
    }

    func testOldBookmarkRootCanAuthorizeTheSameMigratedDirectoryButNotEscape() throws {
        let fm = FileManager.default
        let home = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? fm.removeItem(at: home) }
        let documents = home.appendingPathComponent("Documents", isDirectory: true)
        let current = documents.appendingPathComponent("TradeResearch", isDirectory: true)
        let legacy = documents.appendingPathComponent("FactorTester", isDirectory: true)
        let account = current.appendingPathComponent("users/alice", isDirectory: true)
        try fm.createDirectory(at: account, withIntermediateDirectories: true)
        try fm.createSymbolicLink(at: legacy, withDestinationURL: current)
        let oldAccount = legacy.appendingPathComponent("users/alice", isDirectory: true)
        let document = account.appendingPathComponent("reports/report.md")
        XCTAssertNotNil(PersonalWorkspaceAccessStore.storedAuthorizedRoot(
            path: oldAccount.path, for: document, home: home
        ))
        let outside = home.appendingPathComponent("outside", isDirectory: true)
        try fm.createDirectory(at: outside, withIntermediateDirectories: true)
        try fm.createSymbolicLink(at: account.appendingPathComponent("escape"), withDestinationURL: outside)
        XCTAssertFalse(PersonalWorkspaceAccessStore.physicallyContains(
            account.appendingPathComponent("escape/secret"), in: oldAccount
        ))
    }
}
