import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var notificationsToggleValue = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Refresh") {
                    Picker("Refresh Interval", selection: refreshIntervalBinding) {
                        Text("1 Minute").tag(TimeInterval(60))
                        Text("5 Minutes").tag(TimeInterval(300))
                        Text("10 Minutes").tag(TimeInterval(600))
                        Text("15 Minutes").tag(TimeInterval(900))
                        Text("30 Minutes").tag(TimeInterval(1800))
                        Text("1 Hour").tag(TimeInterval(3600))
                    }
                }

                Section("Radar Source") {
                    Picker("Source", selection: radarSourceBinding) {
                        ForEach(store.settings.radarSources) { source in
                            Text(source.name).tag(source.id)
                        }
                    }
                }

                Section("Notifications") {
                    Toggle("Enable Alert Notifications", isOn: notificationsBinding)

                    Picker("Minimum Severity", selection: notificationSeverityBinding) {
                        ForEach(AlertSeverity.allCases) { severity in
                            Text(severity.displayName).tag(severity)
                        }
                    }
                    .disabled(!store.settings.notificationsEnabled)

                    Button("Refresh Permission Status") {
                        Task {
                            await store.refreshNotificationAuthorizationState()
                            notificationsToggleValue = store.settings.notificationsEnabled
                        }
                    }

                    Text(notificationStatusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("About") {
                    Text("This iPad version is a native SwiftUI rewrite of the desktop weather alert dashboard.")
                    Text("It uses api.weather.gov for alerts and forecast content.")
                }
                .foregroundStyle(.secondary)
            }
            .scrollContentBackground(.hidden)
            .background(BrandBackground())
            .navigationTitle("Settings")
            .toolbarBackground(BrandPalette.skyTop, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .tint(BrandPalette.accent)
            .task {
                notificationsToggleValue = store.settings.notificationsEnabled
                await store.refreshNotificationAuthorizationState()
            }
        }
    }

    private var refreshIntervalBinding: Binding<TimeInterval> {
        Binding(
            get: { store.settings.refreshInterval },
            set: { store.setRefreshInterval($0) }
        )
    }

    private var radarSourceBinding: Binding<UUID> {
        Binding(
            get: { store.settings.selectedRadarSourceID },
            set: { store.setRadarSource(id: $0) }
        )
    }

    private var notificationsBinding: Binding<Bool> {
        Binding(
            get: { notificationsToggleValue },
            set: { newValue in
                notificationsToggleValue = newValue
                Task {
                    await store.setNotificationsEnabled(newValue)
                    notificationsToggleValue = store.settings.notificationsEnabled
                }
            }
        )
    }

    private var notificationSeverityBinding: Binding<AlertSeverity> {
        Binding(
            get: { store.settings.notificationMinimumSeverity },
            set: { store.setNotificationMinimumSeverity($0) }
        )
    }

    private var notificationStatusText: String {
        switch store.notificationAuthorizationState {
        case .authorized:
            return "Notifications are authorized for this app."
        case .denied:
            return "Notifications are denied. Enable them in the iPad Settings app to receive alert banners."
        case .notDetermined:
            return "Notification permission has not been decided yet."
        }
    }
}
