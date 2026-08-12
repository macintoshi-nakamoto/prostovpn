import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var state: AppState

    @AppStorage("prosto.autoconnect") private var autoConnect = false

    @State private var showSettings = false
    @State private var showSupport = false
    @State private var showServers = false

    private var t: L10n { state.t }

    private var canPresent: Bool { !showSettings && !showSupport && !showServers }

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.background.ignoresSafeArea()
                topOrb

                VStack(spacing: 0) {
                    header
                        .fadeUp()

                    Spacer(minLength: 12)

                    VStack(spacing: 28) {
                        PowerButton()
                        statusBlock
                    }
                    .fadeUp(delay: 0.08)

                    Spacer(minLength: 12)

                    CurrentServerCard {
                        if canPresent { showServers = true }
                    }
                    .fadeUp(delay: 0.16)
                    .padding(.horizontal, 20)
                    .padding(.bottom, 8)
                }
            }
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(isPresented: $showSettings) {
                SettingsView()
            }
            .navigationDestination(isPresented: $showSupport) {
                SupportView()
            }
        }
        .sheet(isPresented: $showServers) {
            ServerListSheet()
                .presentationDetents([.height(CGFloat(state.displayServers().count) * 64 + 96)])
                .presentationDragIndicator(.visible)
                .warmSheetBackground()
        }
        .onAppear {
            if autoConnect, !state.didAutoConnect, state.phase == .off {
                state.didAutoConnect = true
                state.toggleConnection()
            }
        }
    }

    private var header: some View {
        HStack {
            GlassCircleButton {
                if canPresent { showSupport = true }
            } content: {
                LogoImage()
                    .frame(width: 27, height: 27)
                    .shadow(color: Theme.accentWarm.opacity(0.45), radius: 8)
            }

            Spacer()

            GlassCircleButton {
                if canPresent { showSettings = true }
            } content: {
                Image(systemName: "gearshape")
                    .font(.system(size: 22, weight: .regular))
                    .foregroundColor(Theme.text.opacity(0.75))
            }
        }
        .padding(.horizontal, 24)
        .padding(.top, 8)
    }

    private var statusBlock: some View {
        VStack(spacing: 4) {
            ZStack {
                Text(statusText)
                    .font(.manrope(24, .extraBold))
                    .kerning(0.3)
                    .foregroundColor(Theme.text)
                    .id(statusText)
                    .transition(.scale(scale: 0.92).combined(with: .opacity))
            }
            .frame(height: 32)

            Text(subText)
                .font(.manrope(14, .medium))
                .foregroundColor(Theme.textMuted)
                .frame(height: 20)
                .monospacedDigit()
                .contentTransition(state.phase == .on ? .numericText() : .opacity)
                .animation(Theme.spring(0.3), value: subText)
        }
        .animation(Theme.spring(0.4), value: statusText)
    }

    private var statusText: String {
        switch state.phase {
        case .off: return t.disconnected
        case .connecting: return t.connectingTxt
        case .on: return t.connected
        }
    }

    private var subText: String {
        switch state.phase {
        case .off: return t.tapToConnect
        case .connecting: return ""
        case .on: return state.formattedDuration
        }
    }

    private var topOrb: some View {
        VStack {
            RadialGradient(
                colors: [Theme.accent.opacity(0.14), .clear],
                center: .center, startRadius: 0, endRadius: 200
            )
            .frame(width: 400, height: 400)
            .blur(radius: 30)
            .offset(y: -140)

            Spacer()
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
    }
}
