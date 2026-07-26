import Foundation
#if os(macOS)
import AppKit
#endif

@MainActor
final class TestJobsController: ObservableObject {
    @Published private(set) var jobs: [TestJob] = []
    @Published private(set) var detail: TestJobDetail?
    @Published private(set) var isLoading = false
    @Published var error: String?
    @Published var notice: String?

    private let service = TestJobsService()

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let loaded = try await service.list()
            jobs = loaded.sorted {
                ($0.updatedAt ?? .distantPast) > ($1.updatedAt ?? .distantPast)
            }
            error = nil
        } catch let failure {
            if jobs.isEmpty { error = failure.localizedDescription }
        }
    }

    func select(_ job: TestJob) async {
        do {
            do {
                detail = try await service.detail(
                    jobID: job.id,
                    port: job.port,
                    fallbackJob: job
                )
            } catch where job.port != currentPort {
                detail = try await service.detail(
                    jobID: job.id,
                    port: currentPort,
                    fallbackJob: job
                )
            }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    func clear(_ job: TestJob) async {
        do {
            do {
                try await service.clearArtifacts(jobID: job.id, port: job.port)
            } catch where job.port != currentPort {
                try await service.clearArtifacts(jobID: job.id, port: currentPort)
            }
            notice = "已清空 \(job.id) 的生成物"
            await select(job)
            await refresh()
        } catch {
            self.error = error.localizedDescription
        }
    }

    func download(_ artifact: TestJobArtifact, from job: TestJob) async {
        do {
            let destination: URL
            do {
                destination = try await service.download(
                    jobID: job.id, port: job.port, artifact: artifact
                )
            } catch where job.port != currentPort {
                destination = try await service.download(
                    jobID: job.id, port: currentPort, artifact: artifact
                )
            }
            openFile(destination)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func downloadAll(from job: TestJob) async {
        do {
            let destination: URL
            do {
                destination = try await service.downloadAll(jobID: job.id, port: job.port)
            } catch where job.port != currentPort {
                destination = try await service.downloadAll(jobID: job.id, port: currentPort)
            }
            openFile(destination)
        } catch {
            self.error = error.localizedDescription
        }
    }

    private var currentPort: Int { Int(ServerConfig.shared.port) ?? 0 }

    private func openFile(_ url: URL) {
#if os(macOS)
        NSWorkspace.shared.open(url)
#endif
    }
}
