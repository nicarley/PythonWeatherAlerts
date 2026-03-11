import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var store: AppStore
    @State private var draft: LocationDraft?

    private let refreshIntervals: [TimeInterval] = [60, 300, 600, 900, 1800, 3600]

    var body: some View {
        NavigationSplitView {
            List(selection: selectedLocationID) {
                Section("Locations") {
                    ForEach(store.settings.locations) { location in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(location.name)
                                .font(.headline)
                            Text(location.query)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .tag(location.id)
                        .contextMenu {
                            Button("Edit") {
                                draft = store.makeDraft(for: location)
                            }
                        }
                    }
                    .onDelete(perform: store.deleteLocations)
                }
            }
            .scrollContentBackground(.hidden)
            .background(BrandBackground())
            .navigationTitle("PyWeatherAlert")
            .toolbarBackground(BrandPalette.skyTop, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbar {
                ToolbarItemGroup(placement: .topBarLeading) {
                    Button {
                        draft = store.makeDraft()
                    } label: {
                        Label("Add", systemImage: "plus")
                    }

                    Button {
                        if let selected = store.selectedLocation {
                            draft = store.makeDraft(for: selected)
                        }
                    } label: {
                        Label("Edit", systemImage: "pencil")
                    }
                    .disabled(store.selectedLocation == nil)
                }

                ToolbarItemGroup(placement: .topBarTrailing) {
                    Picker("Refresh", selection: refreshIntervalBinding) {
                        ForEach(refreshIntervals, id: \.self) { interval in
                            Text(refreshLabel(for: interval)).tag(interval)
                        }
                    }

                    Button {
                        Task {
                            await store.refreshCurrentLocation()
                        }
                    } label: {
                        Label("Refresh", systemImage: "arrow.clockwise")
                    }
                }
            }
        } detail: {
            TabView {
                DashboardView()
                    .tabItem {
                        Label("Dashboard", systemImage: "exclamationmark.triangle")
                    }

                WebTabView(title: "NWS", url: store.nwsURL())
                    .tabItem {
                        Label("NWS", systemImage: "globe")
                    }

                WebTabView(title: "Radar", url: store.radarURL())
                    .tabItem {
                        Label("Radar", systemImage: "dot.radiowaves.left.and.right")
                    }

                SettingsView()
                    .tabItem {
                        Label("Settings", systemImage: "slider.horizontal.3")
                    }
            }
            .navigationTitle(store.selectedLocation?.name ?? "No Location")
            .toolbarBackground(BrandPalette.skyTop, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .tint(BrandPalette.accent)
        }
        .sheet(item: $draft) { currentDraft in
            LocationEditorView(draft: currentDraft) { updatedDraft in
                if await store.saveLocation(from: updatedDraft) {
                    draft = nil
                }
            }
        }
        .task {
            await store.refreshCurrentLocation()
        }
        .task(id: store.settings.refreshInterval) {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(store.settings.refreshInterval * 1_000_000_000))
                await store.refreshCurrentLocation()
            }
        }
        .alert("Unable to Load", isPresented: errorIsPresented) {
            Button("OK") {
                store.errorMessage = nil
            }
        } message: {
            Text(store.errorMessage ?? "Unknown error")
        }
    }

    private var selectedLocationID: Binding<UUID?> {
        Binding<UUID?>(
            get: { store.settings.selectedLocationID },
            set: { newValue in
                guard let newValue else { return }
                store.selectLocation(id: newValue)
                Task {
                    await store.refreshCurrentLocation()
                }
            }
        )
    }

    private var refreshIntervalBinding: Binding<TimeInterval> {
        Binding(
            get: { store.settings.refreshInterval },
            set: { store.setRefreshInterval($0) }
        )
    }

    private var errorIsPresented: Binding<Bool> {
        Binding(
            get: { store.errorMessage != nil },
            set: { if !$0 { store.errorMessage = nil } }
        )
    }

    private func refreshLabel(for interval: TimeInterval) -> String {
        switch Int(interval) {
        case 60:
            return "1 Minute"
        case 300:
            return "5 Minutes"
        case 600:
            return "10 Minutes"
        case 900:
            return "15 Minutes"
        case 1800:
            return "30 Minutes"
        case 3600:
            return "1 Hour"
        default:
            return "\(Int(interval)) sec"
        }
    }
}
