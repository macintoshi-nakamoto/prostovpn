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
    // Состояние общее с делегатом: ссылку `vpn://` система отдаёт именно ему,
    // а применить её должно то же приложение, что видно на экране.
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
            // Пункты меню, которых у VPN-клиента быть не должно: новое окно
            // одного и того же приложения только путает.
            CommandGroup(replacing: .newItem) {}
        }

        MenuBarExtra {
            MenuBarContent()
                .environmentObject(state)
        } label: {
            Image(systemName: menuBarIcon)
        }
    }

    /// Значок в строке меню — единственное, что видно при закрытом окне.
    /// Промежуточные состояния показываем отдельным символом: «щит закрыт» на
    /// половине подключения означал бы, что трафик уже защищён.
    private var menuBarIcon: String {
        switch state.phase {
        case .on: return "lock.shield.fill"
        case .connecting, .disconnecting: return "shield.lefthalf.filled"
        case .off: return "lock.shield"
        }
    }
}

/// Приложение живёт и в строке меню, но закрытие окна не должно означать
/// выход: туннель продолжает работать, и человек ждёт иконку, а не пустоту.
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Без делегата система прячет уведомления, пока приложение впереди,
        // — а обрыв туннеля важен именно в этот момент.
        Notifier.shared.attachDelegate()
    }

    /// Ключ доступа можно просто открыть ссылкой — так его присылают в чате,
    /// и копировать руками ничего не нужно.
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
            // Сессия могла протухнуть, а список стран — измениться, пока
            // приложение было закрыто.
            await state.refreshServers()
            await state.maybeAutoConnect()
        }
    }

    /// Тёплое пятно сверху — единственный декоративный элемент. Оно задаёт
    /// глубину фону, чтобы кнопка не висела на плоском прямоугольнике.
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

/// Тёмное окно без «полупрозрачного» вида системы: приложение задаёт свой
/// фон, и материал под ним только размывал бы градиент.
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

    /// Сколько осталось подписки и трафика — то, ради чего иначе пришлось бы
    /// открывать окно.
    private var subscriptionLine: String? {
        guard let subscription = state.subscription, subscription.active else { return nil }
        var parts: [String] = []
        if let days = subscription.days_left { parts.append(t.days(days)) }
        if let left = subscription.traffic_left_bytes { parts.append(t.bytes(left)) }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}
