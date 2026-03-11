import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                statusCard
                alertsSection
                forecastSection(title: "Hourly Forecast", periods: store.dashboard.hourlyForecast)
                forecastSection(title: "Daily Forecast", periods: store.dashboard.dailyForecast)
            }
            .padding(20)
        }
        .background(BrandBackground())
        .overlay {
            if store.isLoading {
                ProgressView("Loading weather data...")
                    .tint(BrandPalette.accent)
                    .padding(18)
                    .brandCard()
            }
        }
        .refreshable {
            await store.refreshCurrentLocation()
        }
    }

    private var statusCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(store.selectedLocation?.name ?? "No Location Selected")
                .font(.title2.bold())
                .foregroundStyle(BrandPalette.ink)
            Text(store.selectedLocation?.query ?? "")
                .foregroundStyle(BrandPalette.mutedInk)
            if let location = store.selectedLocation {
                Text(ruleSummary(for: location.rules))
                    .font(.caption)
                    .foregroundStyle(BrandPalette.accent)
            }
            if let lastUpdated = store.dashboard.lastUpdated {
                Text("Updated \(lastUpdated.formatted(date: .omitted, time: .shortened))")
                    .font(.caption)
                    .foregroundStyle(BrandPalette.mutedInk)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .brandCard()
    }

    private var alertsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Active Alerts")
                .font(.title3.bold())
                .foregroundStyle(BrandPalette.ink)

            if store.dashboard.alerts.isEmpty {
                ContentUnavailableView(
                    "No Active Alerts",
                    systemImage: "checkmark.shield",
                    description: Text("There are currently no active warnings, watches, or advisories for this location.")
                )
            } else {
                ForEach(store.dashboard.alerts) { alert in
                    AlertCardView(alert: alert)
                }
            }
        }
    }

    private func forecastSection(title: String, periods: [ForecastPeriod]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(.title3.bold())
                .foregroundStyle(BrandPalette.ink)

            if periods.isEmpty {
                ContentUnavailableView(
                    title,
                    systemImage: "cloud.sun",
                    description: Text("Forecast data is not available right now.")
                )
            } else {
                LazyVStack(spacing: 10) {
                    ForEach(periods) { period in
                        ForecastPeriodCard(period: period)
                    }
                }
            }
        }
    }

    private func ruleSummary(for rules: LocationRules) -> String {
        let kinds = rules.enabledKinds
            .filter { $0 != .other }
            .map(\.displayName)
            .joined(separator: ", ")
        return "Showing \(kinds) at \(rules.minimumSeverity.displayName)+"
    }
}

private struct AlertCardView: View {
    let alert: WeatherAlert

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                Text(alert.title)
                    .font(.headline)
                    .foregroundStyle(BrandPalette.ink)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Text(alert.severity)
                    .font(.caption.bold())
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(severityColor.opacity(0.18), in: Capsule())
            }

            Text(alert.summary)
                .font(.subheadline)
                .foregroundStyle(BrandPalette.mutedInk)

            HStack {
                Text(alert.urgency)
                Text(alert.certainty)
                if !alert.expires.isEmpty {
                    Text("Expires \(alert.expires)")
                }
            }
            .font(.caption)
            .foregroundStyle(BrandPalette.mutedInk)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(BrandPalette.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(severityColor.opacity(0.55), lineWidth: 1.2)
        )
    }

    private var severityColor: Color {
        switch alert.kind {
        case .warning:
            return .orange
        case .watch:
            return .blue
        case .advisory:
            return .gray
        case .other:
            return .mint
        }
    }
}

private struct ForecastPeriodCard: View {
    let period: ForecastPeriod

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(period.name)
                        .font(.headline)
                        .foregroundStyle(BrandPalette.ink)
                    Text(period.startTime)
                        .font(.caption)
                        .foregroundStyle(BrandPalette.mutedInk)
                }
                Spacer()
                Text(period.temperatureText)
                    .font(.title3.bold())
                    .foregroundStyle(BrandPalette.accent)
            }

            HStack(spacing: 16) {
                Label(period.windText, systemImage: "wind")
                Label(period.precipitationText, systemImage: "drop")
            }
            .font(.caption)
            .foregroundStyle(BrandPalette.mutedInk)

            Text(period.shortForecast)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(BrandPalette.ink)

            Text(period.detailedForecast)
                .font(.subheadline)
                .foregroundStyle(BrandPalette.mutedInk)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .brandCard()
    }
}
