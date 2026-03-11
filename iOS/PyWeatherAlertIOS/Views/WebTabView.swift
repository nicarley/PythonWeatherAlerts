import SwiftUI
import WebKit

struct WebTabView: View {
    let title: String
    let url: URL?
    @State private var isLoading = true

    var body: some View {
        VStack(spacing: 16) {
            headerCard

            Group {
                if let url {
                    ZStack {
                        EmbeddedWebView(url: url, isLoading: $isLoading)

                        if isLoading {
                            VStack(spacing: 12) {
                                ProgressView()
                                    .tint(BrandPalette.accent)
                                Text("Loading \(title)...")
                                    .font(.headline)
                                    .foregroundStyle(BrandPalette.ink)
                                Text(hostLabel(for: url))
                                    .font(.caption)
                                    .foregroundStyle(BrandPalette.mutedInk)
                            }
                            .padding(24)
                            .brandCard()
                        }
                    }
                } else {
                    ContentUnavailableView(
                        title,
                        systemImage: "globe",
                        description: Text("Select a valid location to load this page.")
                    )
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .stroke(BrandPalette.cardBorder.opacity(0.9), lineWidth: 1)
            )
            .shadow(color: Color.black.opacity(0.08), radius: 18, x: 0, y: 10)
        }
        .padding(20)
        .background(BrandBackground())
        .navigationTitle(title)
        .onChange(of: url) { _, _ in
            isLoading = true
        }
    }

    private var headerCard: some View {
        HStack {
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.title2.bold())
                    .foregroundStyle(BrandPalette.ink)
                Text(headerSubtitle)
                    .font(.subheadline)
                    .foregroundStyle(BrandPalette.mutedInk)
            }
            Spacer()
            Image(systemName: title == "Radar" ? "dot.radiowaves.left.and.right" : "globe.americas.fill")
                .font(.system(size: 24, weight: .semibold))
                .foregroundStyle(BrandPalette.accent)
                .padding(14)
                .background(BrandPalette.accentSoft, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .padding(18)
        .brandCard()
    }

    private var headerSubtitle: String {
        switch title {
        case "Radar":
            return "Interactive weather imagery for the selected source."
        case "NWS":
            return "National Weather Service forecast page for the selected location."
        default:
            return "Live weather web content for the current location."
        }
    }

    private func hostLabel(for url: URL) -> String {
        url.host ?? url.absoluteString
    }
}

struct EmbeddedWebView: UIViewRepresentable {
    let url: URL
    @Binding var isLoading: Bool

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.navigationDelegate = context.coordinator
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        if webView.url != url {
            isLoading = true
            webView.load(URLRequest(url: url))
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(isLoading: $isLoading)
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        @Binding private var isLoading: Bool

        init(isLoading: Binding<Bool>) {
            self._isLoading = isLoading
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            isLoading = false
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            isLoading = false
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            isLoading = false
        }
    }
}
