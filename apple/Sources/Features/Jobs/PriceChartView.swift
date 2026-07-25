import SwiftUI
import Charts

struct PriceChartView: View {
    let bars: [PriceBar]
    @State private var showVolume = true

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("价格查看器").font(.headline)
                Spacer()
                Toggle("Volume", isOn: $showVolume).toggleStyle(.checkbox)
            }
            Chart {
                ForEach(bars) { bar in
                    RuleMark(
                        x: .value("时点", bar.id),
                        yStart: .value("最低", bar.low),
                        yEnd: .value("最高", bar.high)
                    )
                    .foregroundStyle(bar.isUp ? .green : .red)
                    RectangleMark(
                        x: .value("时点", bar.id),
                        yStart: .value("开盘", min(bar.open, bar.close)),
                        yEnd: .value("收盘", max(bar.open, bar.close)),
                        width: .fixed(7)
                    )
                    .foregroundStyle(bar.isUp ? .green : .red)
                }
            }
            .chartYScale(domain: priceDomain)
            .chartXAxis(.hidden)
            .frame(height: 240)
            if showVolume {
                Chart(bars) { bar in
                    BarMark(x: .value("时点", bar.id), y: .value("成交量", bar.volume))
                        .foregroundStyle(bar.isUp ? .green.opacity(0.7) : .red.opacity(0.7))
                }
                .chartYAxis { AxisMarks(position: .leading) }
                .chartXAxis { AxisMarks(values: axisIDs) { value in
                    AxisGridLine()
                    AxisValueLabel { Text(label(for: value.as(Int.self) ?? 0)) }
                } }
                .frame(height: 90)
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.22), in: RoundedRectangle(cornerRadius: 8))
    }

    private var priceDomain: ClosedRange<Double> {
        guard let first = bars.first else { return 0...1 }
        let low = bars.map(\.low).min() ?? first.low
        let high = bars.map(\.high).max() ?? first.high
        let padding = max((high - low) * 0.05, abs(high) * 0.001, 0.000001)
        return (low - padding)...(high + padding)
    }

    private var axisIDs: [Int] {
        guard bars.count > 1 else { return bars.map(\.id) }
        let stride = max(1, bars.count / 5)
        return bars.enumerated().compactMap { index, bar in index % stride == 0 ? bar.id : nil }
    }

    private func label(for id: Int) -> String {
        guard let bar = bars.first(where: { $0.id == id }) else { return "" }
        let formatter = DateFormatter()
        formatter.dateFormat = "MM-dd HH:mm"
        return formatter.string(from: bar.timestamp)
    }
}
