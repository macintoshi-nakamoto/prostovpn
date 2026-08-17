import SwiftUI

/// Экран подключения.
///
/// Одна задача — включить и выключить VPN, поэтому всё, кроме кнопки,
/// прижато к краям: сверху две служебные иконки, снизу выбранный сервер.
struct HomeView: View {
    @EnvironmentObject private var state: AppState
    @Binding var route: Route

    @State private var showServers = false
    @Namespace private var glass

    private var t: L10n { state.t }

    /// Высота слота под карточку сервера. Задана жёстко, потому что на время
    /// раскрытия карточка исчезает — она превращается в шторку. Без
    /// фиксированной высоты кнопка и статус подпрыгивали бы вверх.
    private let serverSlotHeight: CGFloat = 62

    var body: some View {
        ZStack(alignment: .bottom) {
            content

            if showServers {
                backdrop
            }

            // В одной стеклянной ёмкости держим только карточку и шторку.
            // Стёкла внутри ёмкости компонуются общим слоем, и попади туда
            // ещё и кнопка подключения — она рисовалась бы поверх шторки.
            GlassGroup(spacing: 28) {
                ZStack(alignment: .bottom) {
                    if showServers {
                        ServerCurtain(isPresented: $showServers, namespace: glass)
                            .transition(curtainTransition)
                    } else {
                        serverCard
                            .padding(.horizontal, 18)
                            .padding(.bottom, 18)
                            .transition(curtainTransition)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .bottom)
            }
        }
        .onExitCommand { closeServers() }
    }

    private var content: some View {
        VStack(spacing: 0) {
            header
                .fadeUp()

            Spacer(minLength: 8)

            VStack(spacing: 22) {
                PowerButton()
                statusBlock
            }
            .fadeUp(delay: 0.06)

            Spacer(minLength: 8)

            PanelBanners()
                .padding(.horizontal, 18)
                .padding(.bottom, 10)

            if let message = state.errorMessage {
                ErrorBanner(message: message) { state.errorMessage = nil }
                    .padding(.horizontal, 18)
                    .padding(.bottom, 10)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }

            // Пустой слот под карточку: сама карточка живёт в стеклянной
            // ёмкости выше, но место под неё держит эта раскладка — иначе
            // кнопка со статусом прыгали бы при раскрытии шторки.
            Color.clear
                .frame(height: serverSlotHeight + 18)
        }
        .animation(Theme.spring(0.3), value: state.errorMessage)
    }

    /// Затемнение под шторкой. Клик по нему закрывает — на маке это привычнее,
    /// чем искать крестик.
    private var backdrop: some View {
        Color.black.opacity(0.32)
            .ignoresSafeArea()
            .contentShape(Rectangle())
            .onTapGesture { closeServers() }
            .transition(.opacity)
    }

    /// На macOS 26 форму меняет само стекло, поэтому содержимому остаётся
    /// только проявиться. На старых системах перетекать нечему — там шторка
    /// честно выезжает снизу.
    private var curtainTransition: AnyTransition {
        if #available(macOS 26.0, *) {
            return .opacity
        }
        return .move(edge: .bottom).combined(with: .opacity)
    }

    private var header: some View {
        HStack {
            // Каждая кнопка в своей ёмкости: они по разным углам и сливаться
            // им не с чем, зато ёмкость нужна, чтобы стекло пересобиралось
            // при растяжении, а не масштабировалось готовым кадром.
            GlassGroup(spacing: 16) {
                GlassCircleButton(help: t.support) {
                    route = .support
                } content: {
                    LogoImage()
                        .frame(width: 25, height: 25)
                        .shadow(color: Theme.accentWarm.opacity(0.45), radius: 8)
                }
            }

            Spacer()

            if let subscription = state.subscription, subscription.active, let days = subscription.days_left {
                Text("\(days) \(t.subscriptionDays)")
                    .manrope(11, .semibold)
                    .foregroundColor(Theme.textSecondary)
                    .padding(.horizontal, 11)
                    .padding(.vertical, 6)
                    .glassCapsule()
            }

            Spacer()

            GlassGroup(spacing: 16) {
                GlassCircleButton(help: t.settings) {
                    route = .settings
                } content: {
                    Image(systemName: "gearshape")
                        .font(.system(size: 19, weight: .regular))
                        .foregroundColor(Theme.text.opacity(0.75))
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 14)
    }

    private var statusBlock: some View {
        VStack(spacing: 4) {
            Text(statusText)
                .font(.manrope(23, .extraBold))
                .kerning(0.3)
                .foregroundColor(Theme.text)
                .id(statusText)
                .transition(.scale(scale: 0.94).combined(with: .opacity))
                .frame(height: 30)

            Text(subText)
                .manrope(13, .medium)
                .foregroundColor(Theme.textMuted)
                .frame(height: 18)
                .monospacedDigit()
                .contentTransition(state.phase == .on ? .numericText() : .opacity)
                .animation(Theme.spring(0.3), value: subText)
        }
        .animation(Theme.spring(0.35), value: statusText)
    }

    private var statusText: String {
        switch state.phase {
        case .off: return t.disconnected
        case .connecting: return t.connecting
        case .on: return t.connected
        case .disconnecting: return t.disconnecting
        }
    }

    private var subText: String {
        switch state.phase {
        case .off: return state.servers.isEmpty ? t.noServersHint : t.tapToConnect
        case .connecting, .disconnecting: return ""
        case .on: return state.formattedDuration
        }
    }

    // MARK: - Карточка сервера

    private var serverCard: some View {
        Button(action: openServers) {
            HStack(spacing: 12) {
                FlagChip(flag: state.currentServer?.flag ?? "🌐")

                VStack(alignment: .leading, spacing: 2) {
                    Text(state.currentServer?.name(lang: state.lang) ?? t.noServers)
                        .manrope(15, .semibold)
                        .foregroundColor(Theme.text)
                        .lineLimit(1)

                    Text(subtitle)
                        .manrope(12, .medium)
                        .foregroundColor(Theme.textMuted)
                        .lineLimit(1)
                }

                Spacer(minLength: 8)

                if state.currentServer != nil {
                    ProtocolBadge()
                    Image(systemName: "chevron.up")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(Theme.textTertiary)
                }
            }
            .padding(.horizontal, 14)
            .frame(height: serverSlotHeight)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .glassCard(cornerRadius: 20)
        .glassID(HomeGlass.servers, in: glass)
        .fadeUp(delay: 0.12)
        // Карточку можно не только нажать, но и потянуть вверх — шторка
        // едет за курсором, как её потом и закрывают.
        .simultaneousGesture(
            DragGesture(minimumDistance: 6)
                .onEnded { value in
                    if value.translation.height < -12 { openServers() }
                }
        )
        .disabled(state.servers.isEmpty)
        .opacity(state.servers.isEmpty ? 0.6 : 1)
        .transition(curtainTransition)
    }

    private var subtitle: String {
        guard let server = state.currentServer else { return t.noServersHint }
        return server.city(lang: state.lang) ?? server.host
    }

    private func openServers() {
        guard !state.servers.isEmpty else { return }
        withAnimation(.spring(response: 0.42, dampingFraction: 0.78)) {
            showServers = true
        }
    }

    private func closeServers() {
        guard showServers else { return }
        withAnimation(.spring(response: 0.36, dampingFraction: 0.84)) {
            showServers = false
        }
    }
}

/// Сообщения панели между кнопкой и карточкой сервера: обязательное
/// обновление, объяснение пустого списка стран, предупреждение о конце
/// трафика или подписки.
///
/// Без них приложение молчало: человек узнавал, что подписка кончилась, в
/// момент, когда переставали выдаваться страны, — и выглядело это как
/// поломка, а не как «пора продлить». Баннеры не трогают статусный блок:
/// кнопка подключения остаётся главной.
struct PanelBanners: View {
    @EnvironmentObject private var state: AppState

    private var t: L10n { state.t }

    private var showRenew: Bool {
        guard let subscription = state.subscription else { return false }
        return subscription.traffic_low || subscription.expires_soon
    }

    var body: some View {
        VStack(spacing: 8) {
            if state.updates.mandatory { MandatoryUpdateBanner() }
            if !state.notice.isEmpty { NoticeBanner(text: state.notice) }
            if showRenew { RenewBanner() }
        }
        .animation(Theme.spring(0.3), value: state.notice)
        .animation(Theme.spring(0.3), value: showRenew)
    }
}

/// Общая подложка баннеров — тот же тёплый тинт, что у активных карточек.
private struct BannerCard<Content: View>: View {
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(Theme.accentTint12)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

/// Почему список стран пуст — готовый человеческий текст с панели.
/// Здесь его только показывают, не переводя и не сокращая.
private struct NoticeBanner: View {
    let text: String

    var body: some View {
        BannerCard {
            Text(text)
                .manrope(12.5, .semibold)
                .foregroundColor(Theme.accentSoft)
                .fixedSize(horizontal: false, vertical: true)
                .multilineTextAlignment(.leading)
        }
    }
}

/// Трафик или срок подписки на исходе — предупреждение с кнопкой продления.
private struct RenewBanner: View {
    @EnvironmentObject private var state: AppState

    private var t: L10n { state.t }

    /// Трафик важнее срока: без него VPN встанет раньше, чем кончится подписка.
    private var headline: String {
        guard let subscription = state.subscription else { return "" }
        if subscription.traffic_low {
            return t.trafficLow(t.bytes(max(0, subscription.traffic_left_bytes ?? 0)))
        }
        return t.expiresSoon(t.days(subscription.days_left ?? 0))
    }

    var body: some View {
        BannerCard {
            Text(headline)
                .manrope(12.5, .semibold)
                .foregroundColor(Theme.accentSoft)
                .fixedSize(horizontal: false, vertical: true)

            if let address = state.subscription?.renew_url, let url = URL(string: address) {
                Button {
                    NSWorkspace.shared.open(url)
                } label: {
                    Text(t.renew)
                        .manrope(13, .bold)
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 38)
                }
                .buttonStyle(PrimaryButtonStyle(cornerRadius: 12))
                .padding(.top, 10)
            }
        }
    }
}

/// Обязательное обновление — на главном, не только в настройках: без него
/// сервис не работает, и прятать это за шестерёнкой значит оставить человека
/// наедине с молча неработающим VPN.
private struct MandatoryUpdateBanner: View {
    @EnvironmentObject private var state: AppState

    private var t: L10n { state.t }

    var body: some View {
        BannerCard {
            Text(t.updateAvailable(state.updates.info?.version ?? ""))
                .manrope(13, .bold)
                .foregroundColor(Theme.text)

            Text(t.updateMandatory)
                .manrope(12, .medium)
                .foregroundColor(Theme.textMuted)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 2)

            Button {
                state.updates.install()
            } label: {
                Text(updateButtonTitle)
                    .manrope(13, .bold)
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 38)
            }
            .buttonStyle(PrimaryButtonStyle(cornerRadius: 12))
            .padding(.top, 10)
        }
    }

    /// Кнопка сама рассказывает, что происходит: повторное нажатие во время
    /// скачивания install() всё равно игнорирует.
    private var updateButtonTitle: String {
        switch state.updates.stage {
        case .downloading(let percent): return t.updateDownloading(percent)
        case .installing: return t.updateInstalling
        default: return t.updateButton
        }
    }
}

/// Полоса ошибки.
///
/// Говорит, что именно не получилось, и не исчезает сама: молчаливый провал
/// подключения — худшее, что может сделать VPN-клиент.
struct ErrorBanner: View {
    let message: String
    let dismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 13))
                .foregroundColor(Theme.danger)
                .padding(.top, 1)

            Text(message)
                .manrope(12, .medium)
                .foregroundColor(Theme.text.opacity(0.85))
                .fixedSize(horizontal: false, vertical: true)
                .multilineTextAlignment(.leading)

            Spacer(minLength: 4)

            Button(action: dismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundColor(Theme.textTertiary)
                    .frame(width: 20, height: 20)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(Theme.danger.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Theme.danger.opacity(0.25), lineWidth: 1)
        }
    }
}
