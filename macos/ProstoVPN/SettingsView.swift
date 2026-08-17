import SwiftUI
import ServiceManagement

struct SettingsView: View {
    @EnvironmentObject private var state: AppState
    @Binding var route: Route

    @State private var autoConnect = false
    @State private var killSwitch = false
    @State private var useVPNDNS = true
    @State private var launchAtLogin = false
    @State private var splitTunnel = true
    @State private var notifications = true
    @State private var confirmLogout = false

    private var t: L10n { state.t }

    var body: some View {
        VStack(spacing: 0) {
            ScreenHeader(title: t.settings) { route = .home }

            ScrollView {
                VStack(spacing: 14) {
                    serviceCard

                    VStack(spacing: 0) {
                        SettingRow(
                            title: t.split,
                            subtitle: t.splitDesc,
                            isOn: $splitTunnel
                        )
                        CardDivider()
                        tunnelFileRow
                        CardDivider()
                        SettingRow(
                            title: t.kill,
                            subtitle: t.killDesc,
                            isOn: $killSwitch
                        )
                        CardDivider()
                        SettingRow(
                            title: t.useVPNDNS,
                            subtitle: t.useVPNDNSDesc,
                            isOn: $useVPNDNS
                        )
                        CardDivider()
                        SettingRow(
                            title: t.autoconnect,
                            subtitle: t.autoconnectDesc,
                            isOn: $autoConnect
                        )
                        CardDivider()
                        SettingRow(
                            title: t.launchAtLogin,
                            subtitle: t.launchAtLoginDesc,
                            isOn: $launchAtLogin
                        )
                        CardDivider()
                        SettingRow(
                            title: t.notifications,
                            subtitle: t.notificationsDesc,
                            isOn: $notifications
                        )
                    }
                    .cardGroup()

                    languageCard

                    UpdateCard()

                    if state.isLoggedIn {
                        Button {
                            confirmLogout = true
                        } label: {
                            Text(t.logout)
                                .manrope(14, .semibold)
                                .foregroundColor(Theme.danger)
                                .frame(maxWidth: .infinity)
                                .frame(height: 44)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(HoverRowStyle())
                        .background(Theme.danger.opacity(0.08))
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }

                    Text("\(t.version) \(AppInfo.version)")
                        .manrope(11, .medium)
                        .foregroundColor(Theme.textFaint)
                        .padding(.top, 2)
                }
                .padding(.horizontal, 18)
                .padding(.bottom, 20)
            }
        }
        .onAppear {
            killSwitch = state.killSwitch
            useVPNDNS = state.useVPNDNS
            splitTunnel = state.splitTunnel
            autoConnect = state.autoConnect
            notifications = Notifier.shared.enabled
            launchAtLogin = SMAppService.mainApp.status == .enabled
            state.refreshHelperState()
            // Тихий повтор проверки версии: первая идёт на старте приложения,
            // но настройки открывают и через часы после запуска.
            state.updates.check(silent: true)
        }
        .onChange(of: killSwitch) { state.killSwitch = $0 }
        .onChange(of: useVPNDNS) { state.useVPNDNS = $0 }
        .onChange(of: splitTunnel) { state.setSplitTunnel($0) }
        .onChange(of: autoConnect) { state.autoConnect = $0 }
        .onChange(of: notifications) { enableNotifications($0) }
        .onChange(of: launchAtLogin) { setLaunchAtLogin($0) }
        .alert(t.logoutConfirmTitle, isPresented: $confirmLogout) {
            Button(t.no, role: .cancel) {}
            Button(t.yes, role: .destructive) {
                Task {
                    await state.signOut()
                    route = .home
                }
            }
        } message: {
            Text(t.logoutConfirmMessage)
        }
    }

    // MARK: - Служба

    private var serviceCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 9) {
                Circle()
                    .fill(state.helperReady ? Theme.success : Theme.danger)
                    .frame(width: 7, height: 7)

                VStack(alignment: .leading, spacing: 1) {
                    Text(t.service)
                        .manrope(14, .semibold)
                        .foregroundColor(Theme.text)
                    Text(state.helperReady ? t.serviceInstalled : t.serviceMissing)
                        .manrope(11, .medium)
                        .foregroundColor(state.helperReady ? Theme.textMuted : Theme.danger.opacity(0.85))
                }

                Spacer(minLength: 6)

                Button {
                    state.installHelper()
                } label: {
                    Text(state.helperReady ? t.reinstallService : t.installService)
                        .manrope(12, .semibold)
                        .foregroundColor(.white)
                        .padding(.horizontal, 12)
                        .frame(height: 30)
                }
                .buttonStyle(PrimaryButtonStyle(cornerRadius: 9))
                .disabled(state.isBusy)
            }
        }
        .padding(12)
        .cardGroup()
    }

    /// Какой список сетей идёт мимо VPN. Строка ведёт на отдельный экран:
    /// файлов бывает несколько, и в ряду переключателей им тесно.
    private var tunnelFileRow: some View {
        Button {
            route = .splitTunnel
        } label: {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(t.fileRow)
                        .manrope(14, .semibold)
                        .foregroundColor(splitTunnel ? Theme.text : Theme.textMuted)
                    Text(activeFileCaption)
                        .manrope(11, .medium)
                        .foregroundColor(Theme.textMuted)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }

                Spacer(minLength: 8)

                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(Theme.textTertiary)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 11)
            .contentShape(Rectangle())
        }
        .buttonStyle(HoverRowStyle())
        .disabled(!splitTunnel)
        .opacity(splitTunnel ? 1 : 0.5)
    }

    private var activeFileCaption: String {
        guard let file = state.tunnelFiles.active else { return "—" }
        return "\(file.name) · \(file.count) \(t.entries)"
    }

    // MARK: - Язык

    private var languageCard: some View {
        HStack {
            VStack(alignment: .leading, spacing: 1) {
                Text(t.language)
                    .manrope(14, .semibold)
                    .foregroundColor(Theme.text)
                Text(t.langName)
                    .manrope(11, .medium)
                    .foregroundColor(Theme.textMuted)
            }

            Spacer()

            HStack(spacing: 4) {
                langButton("RU", code: "ru")
                langButton("EN", code: "en")
            }
            .padding(3)
            .background(Color.white.opacity(0.05))
            .clipShape(Capsule())
        }
        .padding(12)
        .cardGroup()
    }

    private func langButton(_ title: String, code: String) -> some View {
        let selected = state.lang == code
        return Button {
            state.lang = code
        } label: {
            Text(title)
                .manrope(11, .bold)
                .foregroundColor(selected ? .white : Theme.textSecondary)
                .padding(.horizontal, 11)
                .frame(height: 24)
                .background(selected ? AnyShapeStyle(Theme.accentGradient) : AnyShapeStyle(Color.clear))
                .clipShape(Capsule())
                .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .pointerCursor()
    }

    /// Разрешение спрашиваем сразу при включении: иначе человек включит
    /// переключатель, а система так и не покажет ни одного сообщения.
    private func enableNotifications(_ enabled: Bool) {
        Notifier.shared.enabled = enabled
        if enabled { Notifier.shared.requestPermissionIfNeeded() }
    }

    private func setLaunchAtLogin(_ enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            state.errorMessage = error.localizedDescription
            launchAtLogin = SMAppService.mainApp.status == .enabled
        }
    }
}

// MARK: - Строительные блоки

struct ScreenHeader: View {
    let title: String
    let back: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            GlassGroup(spacing: 16) {
                GlassCircleButton(size: 38, help: nil, action: back) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(Theme.text.opacity(0.85))
                }
            }
            .keyboardShortcut(.escape, modifiers: [])

            Text(title)
                .font(.manrope(19, .extraBold))
                .foregroundColor(Theme.text)

            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.top, 14)
        .padding(.bottom, 12)
    }
}

/// Карточка обновления.
///
/// Показывает результат проверки, а не бодрое «установлена последняя версия»
/// на любой исход: на Windows любая сетевая неудача выглядела именно так, и
/// понять, что проверка вообще не состоялась, было нельзя.
struct UpdateCard: View {
    @EnvironmentObject private var state: AppState

    private var t: L10n { state.t }
    private var updates: UpdateManager { state.updates }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(t.updateTitle)
                        .manrope(14, .semibold)
                        .foregroundColor(Theme.text)

                    Text(statusText)
                        .manrope(11, .medium)
                        .foregroundColor(isFailed ? Theme.danger.opacity(0.85) : Theme.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 8)

                if case .checking = updates.stage {
                    ProgressView()
                        .controlSize(.small)
                        .padding(.top, 2)
                } else if actionTitle != nil {
                    Button {
                        act()
                    } label: {
                        Text(actionTitle ?? "")
                            .manrope(12, .semibold)
                            .foregroundColor(.white)
                            .padding(.horizontal, 12)
                            .frame(height: 30)
                    }
                    .buttonStyle(PrimaryButtonStyle(cornerRadius: 9))
                    .disabled(isWorking)
                }
            }

            if let changelog = updates.info?.changelog?.nilIfEmpty, case .available = updates.stage {
                Text(changelog)
                    .manrope(11, .medium)
                    .foregroundColor(Theme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(12)
        .cardGroup()
    }

    private var isFailed: Bool {
        if case .failed = updates.stage { return true }
        return false
    }

    private var isWorking: Bool {
        switch updates.stage {
        case .downloading, .installing, .checking: return true
        default: return false
        }
    }

    private var statusText: String {
        switch updates.stage {
        case .checking:
            return t.updateChecking
        case .upToDate:
            return "\(t.updateNone) · \(t.updateCurrent) \(AppInfo.version)"
        case .available:
            return t.updateAvailable(updates.info?.version ?? "")
        case .downloading(let percent):
            return t.updateDownloading(percent)
        case .installing:
            return "\(t.updateInstalling) \(t.updateRestartHint)"
        case .failed(let message):
            return message
        }
    }

    private var actionTitle: String? {
        switch updates.stage {
        case .available: return t.updateButton
        case .downloading, .installing: return t.updateButton
        case .failed: return t.updateButton
        case .upToDate, .checking: return nil
        }
    }

    private func act() {
        switch updates.stage {
        case .available: updates.install()
        case .failed: updates.retry()
        default: break
        }
    }
}

struct SettingRow: View {
    let title: String
    let subtitle: String
    @Binding var isOn: Bool
    var enabled: Bool = true

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .manrope(14, .semibold)
                    .foregroundColor(enabled ? Theme.text : Theme.textMuted)
                Text(subtitle)
                    .manrope(11, .medium)
                    .foregroundColor(Theme.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 8)

            Toggle("", isOn: $isOn)
                .labelsHidden()
                .toggleStyle(GlassToggleStyle())
                .disabled(!enabled)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 11)
        .opacity(enabled ? 1 : 0.5)
    }
}
