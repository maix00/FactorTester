// Compile with the production token store. These local symbols shadow Security
// calls so this test never reads or writes the user's real Keychain.
import CryptoKit
import Foundation
import Security

final class ManagerConfig {
    static let shared = ManagerConfig()
    var baseURL: URL? = nil
}

private var values: [String: Data] = [:]
private var writes = 0
private var readFailure: OSStatus?
private var writeFailure: OSStatus?

private func key(_ query: CFDictionary) -> String {
    let item = query as NSDictionary
    return "\(item[kSecAttrService] as? String ?? "")|\(item[kSecAttrAccount] as? String ?? "")"
}
private func key(_ service: String, _ endpoint: URL) -> String {
    let account = SHA256.hash(data: Data(endpoint.absoluteString.utf8)).map { String(format: "%02x", $0) }.joined()
    return "\(service)|\(account)"
}
func SecItemCopyMatching(_ query: CFDictionary, _ result: UnsafeMutablePointer<CFTypeRef?>?) -> OSStatus {
    if let readFailure { return readFailure }
    guard let data = values[key(query)] else { return errSecItemNotFound }
    result?.pointee = data as CFData
    return errSecSuccess
}
func SecItemUpdate(_ query: CFDictionary, _ changes: CFDictionary) -> OSStatus {
    writes += 1
    if let writeFailure { return writeFailure }
    let itemKey = key(query)
    guard values[itemKey] != nil else { return errSecItemNotFound }
    if let data = (changes as NSDictionary)[kSecValueData] as? Data { values[itemKey] = data }
    return errSecSuccess
}
func SecItemAdd(_ query: CFDictionary, _ result: UnsafeMutablePointer<CFTypeRef?>?) -> OSStatus {
    writes += 1
    if let writeFailure { return writeFailure }
    let itemKey = key(query)
    guard values[itemKey] == nil, let data = (query as NSDictionary)[kSecValueData] as? Data else { return errSecDuplicateItem }
    values[itemKey] = data
    return errSecSuccess
}
func SecItemDelete(_ query: CFDictionary) -> OSStatus {
    writes += 1
    values.removeValue(forKey: key(query))
    return errSecSuccess
}

@main struct Check {
    static func main() {
        let first = URL(string: "https://isolated.invalid")!
        let second = URL(string: "https://isolated.invalid:8443")!
        let old = "com.gtht.factortester.manager"
        let current = "com.gtht.traderesearch.manager"
        values[key(old, first)] = Data("legacy-test".utf8)
        precondition(ManagerSessionTokenStore.read(for: first) == "legacy-test")
        precondition(writes == 0 && values[key(old, first)] != nil && values[key(current, first)] == nil)
        precondition(ManagerSessionTokenStore.read(for: second).isEmpty && writes == 0)

        readFailure = errSecInteractionNotAllowed
        precondition(ManagerSessionTokenStore.read(for: first).isEmpty && writes == 0)
        readFailure = nil
        writeFailure = errSecInteractionNotAllowed
        ManagerSessionTokenStore.save("failed-test", for: first)
        precondition(values[key(old, first)] != nil && values[key(current, first)] == nil)
        writeFailure = nil
        ManagerSessionTokenStore.save("current-test", for: first)
        precondition(ManagerSessionTokenStore.read(for: first) == "current-test")
        precondition(values[key(old, first)] == nil && values[key(current, first)] != nil)
        print("PASS: endpoint isolation and read-only, failure-safe Keychain migration")
    }
}
