import Foundation
import XCTest
@testable import FTClient

@MainActor
final class LocalizationTests: XCTestCase {
    func testBundledCatalogExposesSupportedLanguages() {
        let ids = Set(LanguageCatalog.options().map(\.id))

        XCTAssertTrue(ids.contains(AppLanguage.system.rawValue))
        XCTAssertTrue(ids.contains(AppLanguage.english.rawValue))
        XCTAssertTrue(ids.contains(AppLanguage.simplifiedChinese.rawValue))
    }

    func testLanguageIdentifierAcceptsFutureCatalogs() {
        let future = AppLanguage("pt-BR")

        XCTAssertEqual(future.rawValue, "pt-BR")
        XCTAssertTrue(["pt-BR", "pt_BR"].contains(future.locale.identifier))
        XCTAssertNotEqual(future, .system)
    }

    func testLanguageStorePersistsSelectionWithoutUsingGlobalDefaults() {
        let suiteName = "LocalizationTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }

        let store = LanguageStore(defaults: defaults)
        XCTAssertEqual(store.selection, .system)

        store.select(rawValue: AppLanguage.english.rawValue)

        let restored = LanguageStore(defaults: defaults)
        XCTAssertEqual(restored.selection, .english)
        XCTAssertEqual(restored.locale.identifier, "en")
    }

    func testFormatUsesTheSelectedLanguageCatalog() {
        XCTAssertEqual(
            L10n.format(
                "当前版本 %@",
                language: .english,
                arguments: ["0.1.3-beta.32"]
            ),
            "Current version 0.1.3-beta.32"
        )
        XCTAssertEqual(
            L10n.format(
                "当前版本 %@",
                language: .simplifiedChinese,
                arguments: ["0.1.3-beta.32"]
            ),
            "当前版本 0.1.3-beta.32"
        )
    }

}
