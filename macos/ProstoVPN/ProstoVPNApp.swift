import SwiftUI

enum Route {
    case home
    case settings
    case splitTunnel
    case support
}

@main
struct ProstoVPNApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    @StateObject private var state = AppState.shared

    var body: some Scene {
        Window("Prosto VPN", id: "main") {
            RootView()
                .environmentObject(state)
                .frame(width: 380, height: 620)
                .background(WindowBackground())
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentSize)
        .defaultPosition(.center)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }

        MenuBarExtra {
            MenuBarContent()
                .environmentObject(state)
        } label: {
            Image(systemName: menuBarIcon)
        }
    }

    private var menuBarIcon: String {
        switch state.phase {
        case .on: return "lock.shield.fill"
        case .connecting, .disconnecting: return "shield.lefthalf.filled"
        case .off: return "lock.shield"
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        Notifier.shared.attachDelegate()
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        guard let url = urls.first(where: { $0.scheme?.lowercased() == "vpn" }) else { return }
        Task { @MainActor in
            _ = AppState.shared.applyAccessKey(url.absoluteString)
            NSApp.activate(ignoringOtherApps: true)
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var state: AppState
    @State private var route: Route = .home

    var body: some View {
        ZStack {
            Theme.background.ignoresSafeArea()
            topOrb

            if state.isLoggedIn {
                Group {
                    switch route {
                    case .home:
                        HomeView(route: $route)
                    case .settings:
                        SettingsView(route: $route)
                    case .splitTunnel:
                        SplitTunnelView(route: $route)
                    case .support:
                        SupportView(route: $route)
                    }
                }
                .transition(.asymmetric(
                    insertion: .move(edge: route == .home ? .leading : .trailing).combined(with: .opacity),
                    removal: .opacity
                ))
            } else {
                LoginView()
                    .transition(.opacity)
            }

            if state.isBusy && !state.isLoggedIn {
                Color.black.opacity(0.25).ignoresSafeArea()
                ProgressView().controlSize(.large)
            }
        }
        .animation(Theme.spring(0.28), value: route)
        .animation(Theme.spring(0.3), value: state.isLoggedIn)
        .task {
            await state.refreshServers()
            await state.maybeAutoConnect()
        }
    }

    private var topOrb: some View {
        VStack {
            RadialGradient(
                colors: [Theme.accent.opacity(0.14), .clear],
                center: .center, startRadius: 0, endRadius: 180
            )
            .frame(width: 360, height: 360)
            .blur(radius: 30)
            .offset(y: -130)

            Spacer()
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
    }
}

private struct WindowBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            guard let window = view.window else { return }
            window.appearance = NSAppearance(named: .darkAqua)
            window.backgroundColor = NSColor(Theme.bgBottom)
            window.isMovableByWindowBackground = true
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}
}

struct MenuBarContent: View {
    @EnvironmentObject private var state: AppState
    @Environment(\.openWindow) private var openWindow

    private var t: L10n { state.t }

    var body: some View {
        Text(statusLine)

        if let server = state.currentServer {
            Text("\(server.flag) \(server.name(lang: state.lang))")
        }

        if let subscriptionLine {
            Text(subscriptionLine)
        }

        Divider()

        if state.updates.info?.version != nil {
            Button(t.updateAvailable(state.updates.info?.version ?? "")) {
                state.updates.install()
            }
        }

        Button(state.phase == .on || state.phase == .connecting ? t.disconnectAction : t.connectAction) {
            state.toggle()
        }
        .disabled(state.currentServer == nil || state.phase == .disconnecting)

        Button(t.show) {
            NSApp.activate(ignoringOtherApps: true)
            openWindow(id: "main")
        }

        Divider()

        Button(t.quit) {
            Task {
                await state.disconnect()
                NSApp.terminate(nil)
            }
        }
    }

    private var statusLine: String {
        switch state.phase {
        case .off: return t.disconnected
        case .connecting: return t.connecting
        case .on: return "\(t.connected) · \(state.formattedDuration)"
        case .disconnecting: return t.disconnecting
        }
    }

    private var subscriptionLine: String? {
        guard let subscription = state.subscription, subscription.active else { return nil }
        var parts: [String] = []
        if let days = subscription.days_left { parts.append(t.days(days)) }
        if let left = subscription.traffic_left_bytes { parts.append(t.bytes(left)) }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}
