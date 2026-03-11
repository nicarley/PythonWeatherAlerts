import SwiftUI

@main
struct PyWeatherAlertIOSApp: App {
    @StateObject private var store = AppStore()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(store)
        }
    }
}
