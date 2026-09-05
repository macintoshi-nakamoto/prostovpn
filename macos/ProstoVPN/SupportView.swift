import SwiftUI

enum Site {
    static let address = "https://prostovpn.cc"

    static let telegram = "https://t.me/temnoz"
}

struct SupportView: View {
    @EnvironmentObject private var state: AppState
    @Binding var route: Route

    private var t: L10n { state.t }

    var body: some View {
        VStack(spacing: 0) {
            ScreenHeader(title: t.support) { route = .home }

            ScrollView {
                VStack(spacing: 14) {
                    VStack(spacing: 10) {
                        LogoImage()
                            .frame(width: 56, height: 56)
                            .shadow(color: Theme.accentWarm.opacity(0.4), radius: 14)

                        Text("Prosto VPN")
                            .font(.manrope(20, .extraBold))
                            .foregroundColor(Theme.text)

                        Text("\(t.version) \(AppInfo.version)")
                            .manrope(12, .medium)
                            .foregroundColor(Theme.textMuted)
                    }
                    .padding(.top, 4)
                    .padding(.bottom, 6)

                    VStack(spacing: 0) {
                        LinkRow(
                            icon: "paperplane.fill",
                            title: t.tgTitle,
                            subtitle: "@temnoz",
                            url: Site.telegram
                        )
                        CardDivider()
                        LinkRow(
                            icon: "globe",
                            title: t.siteTitle,
                            subtitle: "prostovpn.cc",
                            url: "\(Site.address)/"
                        )
                        CardDivider()
                        LinkRow(
                            icon: "questionmark.circle",
                            title: t.faqTitle,
                            subtitle: t.faqSub,
                            url: "\(Site.address)/faq.html"
                        )
                        CardDivider()
                        LinkRow(
                            icon: "square.and.arrow.down",
                            title: t.downloadsTitle,
                            subtitle: t.downloadsSub,
                            url: "\(Site.address)/download.html"
                        )
                    }
                    .cardGroup()

                    HStack(spacing: 14) {
                        Link(t.privacy, destination: URL(string: "\(Site.address)/privacy.html")!)
                        Link(t.terms, destination: URL(string: "\(Site.address)/offer.html")!)
                    }
                    .manrope(11, .medium)
                    .foregroundColor(Theme.textFaint)
                    .padding(.top, 4)
                }
                .padding(.horizontal, 18)
                .padding(.bottom, 20)
            }
        }
    }
}

struct LinkRow: View {
    let icon: String
    let title: String
    let subtitle: String
    let url: String

    var body: some View {
        Button {
            guard let link = URL(string: url) else { return }
            NSWorkspace.shared.open(link)
        } label: {
            HStack(spacing: 11) {
                Image(systemName: icon)
                    .font(.system(size: 15))
                    .foregroundColor(Theme.accentSoft)
                    .frame(width: 26)

                VStack(alignment: .leading, spacing: 1) {
                    Text(title)
                        .manrope(14, .semibold)
                        .foregroundColor(Theme.text)
                    Text(subtitle)
                        .manrope(11, .medium)
                        .foregroundColor(Theme.textMuted)
                }

                Spacer()

                Image(systemName: "arrow.up.right")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(Theme.textTertiary)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 11)
            .contentShape(Rectangle())
        }
        .buttonStyle(HoverRowStyle())
    }
}
