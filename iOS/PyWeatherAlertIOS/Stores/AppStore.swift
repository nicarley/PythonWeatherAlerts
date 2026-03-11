import Foundation
import SwiftUI
import UserNotifications

@MainActor
final class AppStore: ObservableObject {
    @Published private(set) var settings: AppSettings
    @Published private(set) var dashboard: LocationDashboard
    @Published private(set) var isLoading: Bool
    @Published private(set) var notificationAuthorizationState: NotificationAuthorizationState
    @Published var errorMessage: String?

    private let settingsURL: URL
    private let client = NWSClient()
    private let notificationService = NotificationService()
    private var knownAlertIDsByLocation: [UUID: Set<String>] = [:]

    init() {
        let documentsURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        self.settingsURL = documentsURL.appendingPathComponent("pyweatheralert-ios-settings.json")
        self.settings = Self.loadSettings(from: settingsURL)
        self.dashboard = .empty
        self.isLoading = false
        self.notificationAuthorizationState = .notDetermined
        self.ensureValidSelections()
        Task {
            await refreshNotificationAuthorizationState()
        }
    }

    var selectedLocation: SavedLocation? {
        settings.locations.first(where: { $0.id == settings.selectedLocationID })
    }

    var selectedRadarSource: RadarSource? {
        settings.radarSources.first(where: { $0.id == settings.selectedRadarSourceID })
    }

    func selectLocation(id: UUID) {
        guard settings.selectedLocationID != id else { return }
        settings.selectedLocationID = id
        persist()
    }

    func setRefreshInterval(_ interval: TimeInterval) {
        settings.refreshInterval = interval
        persist()
    }

    func setRadarSource(id: UUID) {
        settings.selectedRadarSourceID = id
        persist()
    }

    func setNotificationsEnabled(_ enabled: Bool) async {
        if enabled {
            let granted = await notificationService.requestAuthorization()
            await refreshNotificationAuthorizationState()
            if !granted {
                errorMessage = "Notifications were not allowed. Enable them in iPad Settings if you want alert banners."
                settings.notificationsEnabled = false
                persist()
                return
            }
        }

        settings.notificationsEnabled = enabled
        persist()
    }

    func setNotificationMinimumSeverity(_ severity: AlertSeverity) {
        settings.notificationMinimumSeverity = severity
        persist()
    }

    func refreshNotificationAuthorizationState() async {
        notificationAuthorizationState = await notificationService.authorizationState()
    }

    func makeDraft(for location: SavedLocation? = nil) -> LocationDraft {
        LocationDraft(
            existingLocation: location,
            name: location?.name ?? "",
            query: location?.query ?? "",
            rules: location?.rules ?? .default
        )
    }

    func saveLocation(from draft: LocationDraft) async -> Bool {
        let trimmedName = draft.name.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedQuery = draft.query.trimmingCharacters(in: .whitespacesAndNewlines)

        guard !trimmedName.isEmpty, !trimmedQuery.isEmpty else {
            errorMessage = "Both the location name and location input are required."
            return false
        }

        do {
            let resolved = try await client.resolveLocation(query: trimmedQuery)
            let updated = SavedLocation(
                id: draft.existingLocation?.id ?? UUID(),
                name: trimmedName,
                query: trimmedQuery,
                latitude: resolved.latitude,
                longitude: resolved.longitude,
                rules: draft.rules
            )

            if let existing = draft.existingLocation,
               let index = settings.locations.firstIndex(where: { $0.id == existing.id }) {
                settings.locations[index] = updated
            } else {
                settings.locations.append(updated)
            }

            settings.selectedLocationID = updated.id
            persist()
            await refreshCurrentLocation()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func deleteLocations(at offsets: IndexSet) {
        settings.locations.remove(atOffsets: offsets)
        if settings.locations.isEmpty {
            settings.locations = [AppSettings.default.locations[0]]
        }
        ensureValidSelections()
        persist()
        Task {
            await refreshCurrentLocation()
        }
    }

    func refreshCurrentLocation() async {
        guard let selectedLocation else { return }
        isLoading = true
        errorMessage = nil

        do {
            let fetchedDashboard = try await client.fetchDashboard(for: selectedLocation)
            let newDashboard = applyRules(selectedLocation.rules, to: fetchedDashboard)
            await notifyForNewAlerts(in: newDashboard, location: selectedLocation)
            dashboard = newDashboard
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    func nwsURL() -> URL? {
        guard let selectedLocation else { return nil }
        return URL(string: "https://forecast.weather.gov/MapClick.php?lat=\(selectedLocation.latitude)&lon=\(selectedLocation.longitude)")
    }

    func radarURL() -> URL? {
        guard let selectedRadarSource else { return nil }
        return URL(string: selectedRadarSource.url)
    }

    private func persist() {
        ensureValidSelections()
        do {
            let data = try JSONEncoder().encode(settings)
            try data.write(to: settingsURL, options: .atomic)
        } catch {
            errorMessage = "Unable to save settings: \(error.localizedDescription)"
        }
    }

    private func ensureValidSelections() {
        if !settings.locations.contains(where: { $0.id == settings.selectedLocationID }),
           let first = settings.locations.first {
            settings.selectedLocationID = first.id
        }

        if !settings.radarSources.contains(where: { $0.id == settings.selectedRadarSourceID }),
           let first = settings.radarSources.first {
            settings.selectedRadarSourceID = first.id
        }
    }

    private static func loadSettings(from url: URL) -> AppSettings {
        guard let data = try? Data(contentsOf: url),
              let decoded = try? JSONDecoder().decode(AppSettings.self, from: data) else {
            return .default
        }
        return decoded
    }

    private func notifyForNewAlerts(in dashboard: LocationDashboard, location: SavedLocation) async {
        let previousIDs = knownAlertIDsByLocation[location.id] ?? []
        let currentIDs = Set(dashboard.alerts.map(\.id))
        let newAlerts = dashboard.alerts.filter { !previousIDs.contains($0.id) }

        if previousIDs.isEmpty {
            knownAlertIDsByLocation[location.id] = currentIDs
            return
        }

        knownAlertIDsByLocation[location.id] = currentIDs

        guard settings.notificationsEnabled,
              notificationAuthorizationState == .authorized else {
            return
        }

        for alert in newAlerts {
            guard let severity = alert.normalizedSeverity,
                  severity.rank >= settings.notificationMinimumSeverity.rank else {
                continue
            }
            await notificationService.sendNotification(for: alert, locationName: location.name)
        }
    }

    private func applyRules(_ rules: LocationRules, to dashboard: LocationDashboard) -> LocationDashboard {
        let filteredAlerts = dashboard.alerts.filter { alert in
            let severityAllowed = (alert.normalizedSeverity?.rank ?? 0) >= rules.minimumSeverity.rank
            let kindAllowed = rules.enabledKinds.contains(alert.kind)
            return severityAllowed && kindAllowed
        }

        return LocationDashboard(
            alerts: filteredAlerts,
            hourlyForecast: dashboard.hourlyForecast,
            dailyForecast: dashboard.dailyForecast,
            lastUpdated: dashboard.lastUpdated
        )
    }
}
