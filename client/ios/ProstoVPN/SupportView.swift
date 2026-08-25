import SwiftUI

struct SupportView: View {
    @EnvironmentObject private var state: AppState
    @Environment(\.openURL) private var openURL

    private var t: L10n { state.t }

    private let site = "https://prostovpn.cc"

    var body: some View {
        ZStack {
            Theme.background.ignoresSafeArea()

            VStack(spacing: 0) {
                VStack(spacing: 2) {
                    LogoImage()
                        .frame(width: 120, height: 80)
                        .shadow(color: Theme.accentWarm.opacity(0.35), radius: 18)

                    Text("Prosto VPN")
                        .font(.manrope(22, .extraBold))
                        .foregroundColor(Theme.text)
                        .padding(.top, -4)

                    Text(t.version)
                        .font(.manrope(13, .medium))
                        .foregroundColor(Theme.textMuted)
                }
                .padding(.top, 18)
                .padding(.bottom, 30)

                VStack(spacing: 0) {
                    linkRow(
                        icon: "paperplane.fill",
                        title: t.tgTitle,
                        subtitle: "@prostovpnn_bot",
                        url: "https://t.me/prostovpnn_bot"
                    )
                    CardDivider()
                    linkRow(
                        icon: "globe",
                        title: t.siteTitle,
                        subtitle: "prostovpn.cc",
                        url: "\(site)/"
                    )
                    CardDivider()
                    linkRow(
                        icon: "questionmark.circle",
                        title: t.faqTitle,
                        subtitle: t.faqSub,
                        url: "\(site)/faq.html"
                    )
                    CardDivider()
                    linkRow(
                        icon: "star",
                        title: t.rateTitle,
                        subtitle: t.rateSub,
                        url: "\(site)/download.html"
                    )
                }
                .cardGroup()

                Spacer()

                footer
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 16)
        }
        .navigationBarTitleDisplayMode(.inline)
    }

    private func linkRow(icon: String, title: String, subtitle: String, url: String) -> some View {
        Button {
            if let link = URL(string: url) {
                openURL(link)
            }
        } label: {
            HStack(spacing: 14) {
                RoundedRectangle(cornerRadius: 11, style: .continuous)
                    .fill(Theme.accentTint12)
                    .frame(width: 38, height: 38)
                    .overlay {
                        Image(systemName: icon)
                            .font(.system(size: 17, weight: .medium))
                            .foregroundColor(Theme.accentSoft)
                    }

                VStack(alignment: .leading, spacing: 1) {
                    Text(title)
                        .font(.manrope(15, .bold))
                        .foregroundColor(Theme.text)
                    Text(subtitle)
                        .font(.manrope(12.5, .medium))
                        .foregroundColor(Theme.textMuted)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(Theme.textTertiary)
            }
            .padding(.vertical, 12)
            .padding(.horizontal, 10)
            .contentShape(Rectangle())
        }
        .buttonStyle(ScaleButtonStyle(scale: 0.98))
    }

    private var footer: some View {
        HStack(spacing: 4) {
            footerLink(t.privacy, url: "\(site)/privacy.html")
            Text("·").foregroundColor(Theme.textFaint)
            footerLink(t.terms, url: "\(site)/offer.html")
        }
        .font(.manrope(12, .regular))
        .frame(maxWidth: .infinity)
    }

    private func footerLink(_ title: String, url: String) -> some View {
        Button {
            if let link = URL(string: url) {
                openURL(link)
            }
        } label: {
            Text(title)
                .foregroundColor(Theme.text.opacity(0.5))
        }
        .buttonStyle(.plain)
    }
}
