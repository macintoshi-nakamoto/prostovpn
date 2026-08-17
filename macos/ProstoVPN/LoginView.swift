import SwiftUI

/// Вход.
///
/// Два пути: аккаунт панели и готовый ключ доступа. Ключ спрятан за
/// раскрытием — большинству он не нужен, но без него приложение бесполезно
/// тем, у кого просто прислали конфиг.
struct LoginView: View {
    @EnvironmentObject private var state: AppState

    @State private var login = ""
    @State private var password = ""
    @State private var accessKey = ""
    @State private var showKeyField = false
    @State private var fieldError: String?

    /// Почему человек снова видит этот экран. Забирается один раз: панель
    /// погасила сессию — устройство отключили из кабинета или админки. Без
    /// объяснения это выглядит как поломка, и человек идёт в поддержку со
    /// «слетел аккаунт».
    @State private var signedOutNotice = ""

    @FocusState private var focus: Field?

    private enum Field { case login, password, key }

    private var t: L10n { state.t }

    var body: some View {
        VStack(spacing: 0) {
            Spacer(minLength: 24)

            VStack(spacing: 10) {
                LogoImage()
                    .frame(width: 56, height: 56)
                    .shadow(color: Theme.accentWarm.opacity(0.5), radius: 18)

                Text("Prosto VPN")
                    .font(.manrope(24, .extraBold))
                    .foregroundColor(Theme.text)

                Text(t.tagline)
                    .manrope(13, .medium)
                    .foregroundColor(Theme.textMuted)
            }
            .fadeUp()

            Spacer(minLength: 24)

            if !signedOutNotice.isEmpty {
                Text(signedOutNotice)
                    .manrope(12, .semibold)
                    .foregroundColor(Theme.accentSoft)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(Theme.accentTint12)
                    .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .padding(.horizontal, 28)
                    .padding(.bottom, 14)
                    .transition(.opacity)
            }

            VStack(spacing: 10) {
                FieldBox(focused: focus == .login, invalid: fieldError == t.errEmptyLogin) {
                    TextField(t.loginPlaceholder, text: $login)
                        .focused($focus, equals: .login)
                        .onSubmit { focus = .password }
                }

                FieldBox(focused: focus == .password, invalid: fieldError == t.errShortPassword) {
                    SecureField(t.passwordPlaceholder, text: $password)
                        .focused($focus, equals: .password)
                        .onSubmit(submit)
                }

                Button(action: submit) {
                    Text(state.isBusy ? t.signingIn : t.signIn)
                        .manrope(15, .bold)
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 46)
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(state.isBusy)
                .padding(.top, 2)

                keySection
            }
            .padding(.horizontal, 28)
            .fadeUp(delay: 0.08)

            if let message = fieldError ?? state.errorMessage {
                Text(message)
                    .manrope(12, .medium)
                    .foregroundColor(Theme.danger)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 28)
                    .padding(.top, 12)
                    .transition(.opacity)
            }

            Spacer(minLength: 20)

            terms
                .padding(.bottom, 18)
        }
        .animation(Theme.spring(0.25), value: showKeyField)
        .animation(Theme.spring(0.25), value: fieldError)
        .animation(Theme.spring(0.25), value: signedOutNotice)
        .onAppear {
            focus = .login
            signedOutNotice = state.consumeSignedOutReason()
        }
    }

    @ViewBuilder
    private var keySection: some View {
        if showKeyField {
            VStack(spacing: 8) {
                FieldBox(focused: focus == .key) {
                    TextField(t.keyPlaceholder, text: $accessKey)
                        .focused($focus, equals: .key)
                        .onSubmit(applyKey)
                }

                Button(action: applyKey) {
                    Text(t.applyKey)
                        .manrope(13, .semibold)
                        .foregroundColor(Theme.link)
                }
                .buttonStyle(.plain)
                .pointerCursor()
            }
            .padding(.top, 6)
            .transition(.move(edge: .top).combined(with: .opacity))
        } else {
            Button {
                showKeyField = true
                focus = .key
            } label: {
                Text(t.orKey)
                    .manrope(12, .medium)
                    .foregroundColor(Theme.textSecondary)
            }
            .buttonStyle(.plain)
            .pointerCursor()
            .padding(.top, 6)
        }
    }

    private var terms: some View {
        HStack(spacing: 0) {
            Text(t.termsPrefix)
                .foregroundColor(Theme.textFaint)
            Link(t.termsLink, destination: URL(string: "\(Site.address)/offer.html")!)
                .foregroundColor(Theme.link.opacity(0.75))
        }
        .manrope(11, .medium)
    }

    private func submit() {
        fieldError = nil
        let cleanLogin = login.trimmingCharacters(in: .whitespacesAndNewlines)

        // Ключ иногда вставляют прямо в поле логина — не заставляем искать,
        // куда его на самом деле класть.
        if cleanLogin.lowercased().hasPrefix("vpn://") || cleanLogin.contains("[Interface]") {
            accessKey = cleanLogin
            applyKey()
            return
        }

        guard !cleanLogin.isEmpty else {
            fieldError = t.errEmptyLogin
            focus = .login
            return
        }
        guard password.count >= 4 else {
            fieldError = t.errShortPassword
            focus = .password
            return
        }

        Task { await state.login(login: cleanLogin, password: password) }
    }

    private func applyKey() {
        fieldError = nil
        let raw = accessKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return }
        if !state.applyAccessKey(raw) {
            fieldError = t.errBadKey
        }
    }
}

extension View {
    /// Курсор-рука на всём, что кликается: без него текстовая ссылка на маке
    /// не читается как ссылка.
    func pointerCursor() -> some View {
        onHover { inside in
            if inside { NSCursor.pointingHand.push() } else { NSCursor.pop() }
        }
    }
}
