import SwiftUI
import Charts

struct PriceChartView: View {
    let bars: [PriceBar]
    let visibleInterval: ClosedRange<Date>?
    @State private var showVolume = true
    @State private var renderedBars: [PriceBar] = []
    @State private var hasCompletedSampling = false

    init(
        bars: [PriceBar], visibleInterval: ClosedRange<Date>? = nil
    ) {
        self.bars = bars
        self.visibleInterval = visibleInterval
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("价格查看器").font(.headline)
                Spacer()
                Toggle("Volume", isOn: $showVolume).toggleStyle(.checkbox)
            }
            GeometryReader { geometry in
                let budget = PriceBarViewportSampler.barBudget(
                    pixelWidth: Double(geometry.size.width)
                )
                Group {
                    if !renderedBars.isEmpty {
                        charts
                    } else if hasCompletedSampling {
                        Text("当前可见区间没有行情数据")
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else {
                        ProgressView("正在准备行情图…")
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                }
                .task(id: samplingKey(barBudget: budget)) {
                    await sampleBars(maximumBarCount: budget)
                }
            }
            .frame(height: showVolume ? 338 : 240)
            Text(L10n.format(
                "当前按视图宽度聚合显示 %d / %d 根 K 线",
                renderedBars.count,
                visibleBarCount
            ))
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(12)
        .background(.quaternary.opacity(0.22), in: RoundedRectangle(cornerRadius: 8))
    }

    @ViewBuilder
    private var charts: some View {
        VStack(spacing: 8) {
            Chart {
                ForEach(renderedBars) { bar in
                    RuleMark(
                        x: .value(L10n.text("时点"), bar.id),
                        yStart: .value(L10n.text("最低"), bar.low),
                        yEnd: .value(L10n.text("最高"), bar.high)
                    )
                    .foregroundStyle(bar.isUp ? .green : .red)
                    RectangleMark(
                        x: .value(L10n.text("时点"), bar.id),
                        yStart: .value(L10n.text("开盘"), min(bar.open, bar.close)),
                        yEnd: .value(L10n.text("收盘"), max(bar.open, bar.close)),
                        width: .fixed(7)
                    )
                    .foregroundStyle(bar.isUp ? .green : .red)
                }
            }
            .chartYScale(domain: priceDomain)
            .chartXAxis(.hidden)
            .frame(height: 240)
            if showVolume {
                Chart(renderedBars) { bar in
                    BarMark(
                        x: .value(L10n.text("时点"), bar.id),
                        y: .value(L10n.text("成交量"), bar.volume)
                    )
                    .foregroundStyle(
                        bar.isUp ? .green.opacity(0.7) : .red.opacity(0.7)
                    )
                }
                .chartYAxis { AxisMarks(position: .leading) }
                .chartXAxis { AxisMarks(values: axisIDs) { value in
                    AxisGridLine()
                    AxisValueLabel { Text(label(for: value.as(Int.self) ?? 0)) }
                } }
                .frame(height: 90)
            }
        }
    }

    private var priceDomain: ClosedRange<Double> {
        guard let first = renderedBars.first else { return 0...1 }
        let low = renderedBars.lazy.map(\.low).min() ?? first.low
        let high = renderedBars.lazy.map(\.high).max() ?? first.high
        let padding = max((high - low) * 0.05, abs(high) * 0.001, 0.000001)
        return (low - padding)...(high + padding)
    }

    private var axisIDs: [Int] {
        guard renderedBars.count > 1 else { return renderedBars.map(\.id) }
        let stride = max(1, renderedBars.count / 5)
        return renderedBars.enumerated().compactMap { index, bar in
            index.isMultiple(of: stride) ? bar.id : nil
        }
    }

    private func label(for id: Int) -> String {
        guard let bar = renderedBars.first(where: { $0.id == id }) else { return "" }
        return Self.axisDateFormatter.string(from: bar.timestamp)
    }

    private var visibleBarCount: Int {
        PriceBarViewportSampler.visibleBarCount(
            in: bars,
            interval: visibleInterval
        )
    }

    private func samplingKey(barBudget: Int) -> SamplingKey {
        SamplingKey(
            barBudget: barBudget,
            barCount: bars.count,
            firstBar: bars.first,
            lastBar: bars.last,
            intervalLowerBound: visibleInterval?.lowerBound,
            intervalUpperBound: visibleInterval?.upperBound
        )
    }

    @MainActor
    private func sampleBars(maximumBarCount: Int) async {
        do {
            let sampled = try await PriceBarViewportSampler.sampleInBackground(
                bars,
                visibleInterval: visibleInterval,
                maximumBarCount: maximumBarCount
            )
            try Task.checkCancellation()
            renderedBars = sampled
            hasCompletedSampling = true
        } catch is CancellationError {
            return
        } catch {
            renderedBars = []
            hasCompletedSampling = true
        }
    }

    private static let axisDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "MM-dd HH:mm"
        return formatter
    }()

    private struct SamplingKey: Hashable {
        let barBudget: Int
        let barCount: Int
        let firstBar: PriceBar?
        let lastBar: PriceBar?
        let intervalLowerBound: Date?
        let intervalUpperBound: Date?
    }
}
