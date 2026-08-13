import Foundation
import SwiftUI

/// A language identifier backed by the bundled String Catalog.
///
/// This is deliberately not a closed enum: adding a localization in
/// `Localizable.xcstrings` makes the language discoverable without changing
/// view code.
struct AppLanguage: RawRepresentable, Hashable, Identifiable, Sendable {
    let rawValue: String

    init?(rawValue: String) {
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }
        self.rawValue = value
    }

    init(_ rawValue: String) {
        self.rawValue = rawValue
    }

    static let system = AppLanguage("system")
    static let simplifiedChinese = AppLanguage("zh-Hans")
    static let english = AppLanguage("en")

    var id: String { rawValue }

    var locale: Locale {
        self == .system ? .autoupdatingCurrent : Locale(identifier: rawValue)
    }
}

struct LanguageOption: Identifiable, Hashable, Sendable {
    let id: String
    let titleKey: String

    var language: AppLanguage { AppLanguage(id) }
}

enum LanguageCatalog {
    static func options(bundle: Bundle = .main) -> [LanguageOption] {
        let localizedIdentifiers = bundle.localizations
            .filter { $0.caseInsensitiveCompare("Base") != .orderedSame }
            .sorted()
        var result = [LanguageOption(id: AppLanguage.system.rawValue, titleKey: "跟随系统")]
        for identifier in localizedIdentifiers where identifier != AppLanguage.system.rawValue {
            let titleKey: String
            switch identifier {
            case AppLanguage.simplifiedChinese.rawValue:
                titleKey = "简体中文"
            case AppLanguage.english.rawValue:
                titleKey = "English"
            default:
                titleKey = Locale(identifier: identifier)
                    .localizedString(forIdentifier: identifier)
                    ?? identifier
            }
            result.append(LanguageOption(id: identifier, titleKey: titleKey))
        }
        return result
    }
}

@MainActor
final class LanguageStore: ObservableObject {
    nonisolated static let defaultsKey = "client.language"

    @Published var selection: AppLanguage {
        didSet {
            defaults.set(selection.rawValue, forKey: Self.defaultsKey)
            guard !isApplyingPreference, let principal else { return }
            defaults.set(selection.rawValue, forKey: userKey(principal))
        }
    }

    private let defaults: UserDefaults
    private let preferences: any UserLanguagePreferenceAPI
    private var principal: String?
    private var isApplyingPreference = false

    init(
        defaults: UserDefaults = .standard,
        preferences: any UserLanguagePreferenceAPI = ManagerUserLanguagePreferenceClient()
    ) {
        self.defaults = defaults
        self.preferences = preferences
        self.selection = defaults.string(forKey: Self.defaultsKey)
            .flatMap(AppLanguage.init(rawValue:)) ?? .system
    }

    var locale: Locale { selection.locale }

    func select(rawValue: String) {
        guard let language = AppLanguage(rawValue: rawValue) else { return }
        selection = language
        guard let principal else { return }
        Task {
            try? await preferences.update(
                language: language,
                principal: principal
            )
        }
    }

    func synchronize(principal value: String?) async {
        let normalized = value?.trimmingCharacters(in: .whitespacesAndNewlines)
        principal = normalized?.isEmpty == false ? normalized : nil
        let ownerScoped = principal.flatMap(ownerScopedLanguage(for:))
        if let ownerScoped {
            apply(ownerScoped)
        } else if principal == nil {
            apply(lastCachedLanguage())
        }
        guard let principal else { return }
        if let remote = try? await preferences.read(principal: principal) {
            if remote.configured {
                apply(remote.language)
                defaults.set(
                    remote.language.rawValue,
                    forKey: userKey(principal)
                )
            } else if let ownerScoped {
                // Only an owner-scoped value is safe to bootstrap. The global
                // last selection may belong to another account on this Mac.
                apply(ownerScoped)
                try? await preferences.update(
                    language: ownerScoped,
                    principal: principal
                )
            } else {
                apply(remote.language)
            }
        }
    }

    private func lastCachedLanguage() -> AppLanguage {
        defaults.string(forKey: Self.defaultsKey)
            .flatMap(AppLanguage.init(rawValue:)) ?? selection
    }

    private func ownerScopedLanguage(for principal: String) -> AppLanguage? {
        defaults.string(forKey: userKey(principal))
            .flatMap(AppLanguage.init(rawValue:))
    }

    private func apply(_ language: AppLanguage) {
        isApplyingPreference = true
        selection = language
        isApplyingPreference = false
    }

    private func userKey(_ principal: String) -> String {
        "\(Self.defaultsKey).user.\(principal)"
    }
}

enum L10n {
    static func resource(_ key: String) -> LocalizedStringResource {
        LocalizedStringResource(
            String.LocalizationValue(key),
            table: "Localizable",
            bundle: .main
        )
    }

    static var locale: Locale {
        effectiveLanguage.locale
    }

    static func text(_ key: String) -> String {
        localizedText(key, language: effectiveLanguage)
    }

    /// Resolve a label from the language selected for the current UI session.
    /// Views observing ``LanguageStore`` use this overload so a selection
    /// change is reflected before the preference write has completed.
    static func text(_ key: String, language: AppLanguage) -> String {
        localizedText(key, language: language)
    }

    static func format(_ key: String, _ arguments: CVarArg...) -> String {
        String(format: text(key), locale: locale, arguments: arguments)
    }

    static func format(
        _ key: String,
        language: AppLanguage,
        arguments: [CVarArg]
    ) -> String {
        let localized = localizedText(key, language: language)
        return String(
            format: localized,
            locale: language.locale,
            arguments: arguments
        )
    }

    private static func localizedText(
        _ key: String,
        language: AppLanguage
    ) -> String {
        if language == .system {
            return Bundle.main.localizedString(
                forKey: key,
                value: nil,
                table: "Localizable"
            )
        }
        if let resourceURL = Bundle.main.url(
            forResource: language.rawValue,
            withExtension: "lproj"
        ), let localizedBundle = Bundle(url: resourceURL) {
            return localizedBundle.localizedString(
                forKey: key,
                value: key,
                table: "Localizable"
            )
        }
        return Bundle.main.localizedString(
            forKey: key,
            value: key,
            table: "Localizable"
        )
    }

    private static var effectiveLanguage: AppLanguage {
        UserDefaults.standard.string(forKey: LanguageStore.defaultsKey)
            .flatMap(AppLanguage.init(rawValue:)) ?? .system
    }
}
