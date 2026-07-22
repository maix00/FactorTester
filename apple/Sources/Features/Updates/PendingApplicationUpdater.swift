import AppKit
import Foundation

enum PendingApplicationUpdater {
    /// Start a tiny parent-independent updater, then let the current App quit.
    /// The helper only accepts a bundle staged and signature-verified by the
    /// client; it never downloads or trusts a path supplied by the UI.
    @MainActor
    static func launch(
        pending: PendingApplicationUpdate,
        currentBundle: URL
    ) throws {
        let staged = URL(fileURLWithPath: pending.appPath)
        guard FileManager.default.fileExists(atPath: staged.path),
              currentBundle.pathExtension == "app" else {
            throw AppUpdateError.invalidRelease
        }
        let script = #"""
        parent="$1"
        staged="$2"
        target="$3"
        temporary="${target}.updating"
        backup="${target}.previous"
        while kill -0 "$parent" 2>/dev/null; do sleep 0.25; done
        /usr/bin/ditto --rsrc --preserveHFSCompression "$staged" "$temporary" || exit 1
        /usr/bin/codesign --verify --deep --strict "$temporary" || exit 1
        new_requirement=$(/usr/bin/codesign -dr - "$temporary" 2>&1 | /usr/bin/sed -n 's/^designated => //p')
        old_requirement=$(/usr/bin/codesign -dr - "$target" 2>&1 | /usr/bin/sed -n 's/^designated => //p')
        test -n "$new_requirement" || exit 1
        test "$new_requirement" = "$old_requirement" || exit 1
        if [ -e "$backup" ]; then /bin/rm -rf "$backup"; fi
        /bin/mv "$target" "$backup" || exit 1
        /bin/mv "$temporary" "$target" || { /bin/mv "$backup" "$target"; exit 1; }
        /usr/bin/open -n "$target"
        """#
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/sh")
        process.arguments = [
            "-c", script, "ftclient-updater",
            String(ProcessInfo.processInfo.processIdentifier),
            staged.path,
            currentBundle.path,
        ]
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        NSApp.terminate(nil)
    }
}
