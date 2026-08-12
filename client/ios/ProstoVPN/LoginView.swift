import SwiftUI

struct LoginView: View {
    @EnvironmentObject private var state: AppState

    @State private var login = ""
    @State private var password = ""
    @State private var showPassword = false
    @State private var errorText = ""
    @State private var isLoading = false
    @State private var isDone = false

    @FocusState private var focusedField: Field?

    enum Field {
        case login, password
    }

    private var t: L10n { state.t }

    var body: some View {
        ZStack {
            FloatingOrbs()

            GeometryReader { proxy in
                ScrollView(showsIndicators: false) {
                    VStack(spacing: 0) {
                        header
                            .padding(.top, 44)
                            .fadeUp()

                        Spacer(minLength: 24)

                        VStack(spacing: 12) {
                            form
                            if !errorText.isEmpty {
                                Text(errorText)
                                    .font(.manrope(13, .semibold))
                                    .foregroundColor(Theme.accentSoft)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(.horizontal, 8)
                            }
                            submitButton
                            guestButton
                        }
                        .fadeUp(delay: 0.12)

                        footer
                            .padding(.top, 28)
                            .fadeUp(delay: 0.22)
                    }
                    .padding(.horizontal, 28)
                    .padding(.top, 24)
                    .padding(.bottom, 40)
                    .frame(minHeight: proxy.size.height)
                }
                .scrollBounceBehavior(.basedOnSize)
            }
        }
    }

    private var header: some View {
        VStack(spacing: 4) {
            LogoImage()
                .frame(width: 190, height: 127)
                .shadow(color: Theme.accentWarm.opacity(0.35), radius: 24)

            Text("Prosto VPN")
                .font(.manrope(28, .extraBold))
                .kerning(0.5)
                .foregroundColor(Theme.text)
                .padding(.top, -8)

            Text(t.tagline)
                .font(.manrope(14, .medium))
                .foregroundColor(Theme.textSecondary)
        }
    }

    private var form: some View {
        VStack(spacing: 10) {
            fieldRow(focused: focusedField == .login) {
                Image(systemName: "person")
                    .font(.system(size: 19, weight: .regular))
                    .foregroundColor(Theme.textMuted)
                    .frame(width: 22)

                TextField("", text: $login, prompt: placeholder(t.loginPlaceholder))
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.next)
                    .focused($focusedField, equals: .login)
                    .foregroundColor(Theme.text)
                    .font(.manrope(16, .medium))
                    .tint(Theme.link)
                    .onChange(of: login) { _ in errorText = "" }
                    .onSubmit { focusedField = .password }
            }
            .onTapGesture { focusedField = .login }

            Rectangle()
                .fill(Theme.divider)
                .frame(height: 1)
                .padding(.horizontal, 4)

            fieldRow(focused: focusedField == .password) {
                Image(systemName: "lock")
                    .font(.system(size: 19, weight: .regular))
                    .foregroundColor(Theme.textMuted)
                    .frame(width: 22)

                Group {
                    if showPassword {
                        TextField("", text: $password, prompt: placeholder(t.passwordPlaceholder))
                    } else {
                        SecureField("", text: $password, prompt: placeholder(t.passwordPlaceholder))
                    }
                }
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.go)
                .focused($focusedField, equals: .password)
                .foregroundColor(Theme.text)
                .font(.manrope(16, .medium))
                .tint(Theme.link)
                .onChange(of: password) { _ in errorText = "" }
                .onSubmit(submit)

                Button {
                    showPassword.toggle()
                } label: {
                    Image(systemName: showPassword ? "eye" : "eye.slash")
                        .font(.system(size: 17, weight: .regular))
                        .foregroundColor(Theme.textMuted)
                        .frame(width: 32, height: 44)
                }
            }
            .onTapGesture { focusedField = .password }
        }
    }

    private func placeholder(_ text: String) -> Text {
        Text(text)
            .font(.manrope(16, .medium))
            .foregroundColor(Theme.text.opacity(0.32))
    }

    private func fieldRow<Content: View>(
        focused: Bool,
        @ViewBuilder content: () -> Content
    ) -> some View {
        HStack(spacing: 12) {
            content()
        }
        .padding(.horizontal, 14)
        .frame(height: 52)
        .background(focused ? Theme.rowActive : .clear)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .animation(.easeOut(duration: 0.2), value: focused)
        .contentShape(Rectangle())
    }

    private var submitButton: some View {
        Button(action: submit) {
            Text(isLoading ? t.signingIn : (isDone ? t.signInDone : t.signIn))
                .font(.manrope(17, .bold))
                .foregroundColor(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 56)
                .opacity(isLoading ? 0.7 : 1)
                .background(isDone ? AnyShapeStyle(Theme.successGradient) : AnyShapeStyle(Theme.accentGradient))
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(
                            LinearGradient(
                                colors: [Color.white.opacity(0.25), .clear],
                                startPoint: .top, endPoint: .center
                            ),
                            lineWidth: 1
                        )
                }
                .shadow(color: Theme.accent.opacity(0.35), radius: 14, y: 8)
                .animation(.easeInOut(duration: 0.3), value: isDone)
                .animation(.easeInOut(duration: 0.2), value: isLoading)
        }
        .buttonStyle(ScaleButtonStyle(scale: 0.98))
        .disabled(isLoading || isDone)
    }

    private var guestButton: some View {
        Button {
            focusedField = nil
            state.loginAsGuest()
        } label: {
            Text(t.continueWithoutAccount)
                .font(.manrope(14, .semibold))
                .foregroundColor(Theme.textSecondary)
                .frame(maxWidth: .infinity)
                .frame(height: 40)
                .contentShape(Rectangle())
        }
        .buttonStyle(ScaleButtonStyle(scale: 0.98))
        .disabled(isLoading || isDone)
    }

    private var footer: some View {
        (Text(t.termsPrefix)
            .foregroundColor(Theme.textFaint)
        + Text(t.termsLink)
            .foregroundColor(Theme.text.opacity(0.5)))
            .font(.manrope(12, .regular))
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity)
    }

    private func submit() {
        guard !isLoading, !isDone else { return }

        let credentials = login.trimmingCharacters(in: .whitespacesAndNewlines)

        if credentials.isEmpty {
            errorText = t.errEmptyLogin
            return
        }
        if !credentials.hasPrefix("vpn://"), password.count < 4 {
            errorText = t.errShortPassword
            return
        }

        focusedField = nil
        errorText = ""
        isLoading = true

        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 1_200_000_000)

            let joined = credentials.components(separatedBy: .whitespacesAndNewlines).joined()
            if joined.hasPrefix("vpn://"), AppState.extractServer(fromAccessKey: joined) == nil {
                isLoading = false
                errorText = t.errBadKey
                return
            }

            isLoading = false
            isDone = true

            try? await Task.sleep(nanoseconds: 450_000_000)
            try? state.login(credentials: credentials)
        }
    }
}

private struct FloatingOrbs: View {
    @State private var drift = false

    var body: some View {
        GeometryReader { geo in
            ZStack {
                RadialGradient(
                    colors: [Theme.accent.opacity(0.2), .clear],
                    center: .center, startRadius: 0, endRadius: 170
                )
                .frame(width: 340, height: 340)
                .scaleEffect(drift ? 1.15 : 1)
                .position(x: 90, y: 50)
                .offset(x: drift ? 30 : 0, y: drift ? -40 : 0)
                .animation(.easeInOut(duration: 9).repeatForever(autoreverses: true), value: drift)

                RadialGradient(
                    colors: [Theme.accentWarm.opacity(0.14), .clear],
                    center: .center, startRadius: 0, endRadius: 150
                )
                .frame(width: 300, height: 300)
                .scaleEffect(drift ? 1.1 : 1)
                .position(x: geo.size.width - 50, y: geo.size.height - 200)
                .offset(x: drift ? -40 : 0, y: drift ? 30 : 0)
                .animation(.easeInOut(duration: 11).repeatForever(autoreverses: true), value: drift)
            }
            .blur(radius: 30)
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
        .onAppear { drift = true }
    }
}
