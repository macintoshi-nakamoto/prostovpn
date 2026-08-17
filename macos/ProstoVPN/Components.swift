import SwiftUI

// MARK: - Стекло

/*
 Liquid Glass — системный, из macOS 26. Своей имитации нет: у настоящего
 стекла собственная реакция на нажатие и наведение, и подменять её
 масштабированием — ровно то, из-за чего интерфейс перестаёт ощущаться
 родным.

 На Sonoma и Sequoia остаётся запасной вариант из материала и обводки —
 иначе приложение просто не запустится.
 */

/// Общая «ёмкость» для стеклянных элементов.
///
/// Внутри неё соседние стёкла ведут себя как капли одной жидкости: сходятся,
/// сливаются и растягиваются друг в друга. Без ёмкости каждый элемент живёт
/// сам по себе, и перетекание карточки в шторку невозможно в принципе.
struct GlassGroup<Content: View>: View {
    var spacing: CGFloat = 24
    @ViewBuilder var content: () -> Content

    var body: some View {
        if #available(macOS 26.0, *) {
            GlassEffectContainer(spacing: spacing) { content() }
        } else {
            content()
        }
    }
}

extension View {
    @ViewBuilder
    func glassCircle(interactive: Bool = true, tint: Color? = nil) -> some View {
        if #available(macOS 26.0, *) {
            glassEffect(glass(interactive: interactive, tint: tint), in: .circle)
        } else {
            background {
                ZStack {
                    Circle().fill(.ultraThinMaterial)
                    Circle().fill(
                        LinearGradient(
                            colors: [Color.white.opacity(0.12), Color.white.opacity(0.04)],
                            startPoint: .top, endPoint: .bottom
                        )
                    )
                    if let tint {
                        Circle().fill(tint.opacity(0.22))
                    }
                }
            }
            .clipShape(Circle())
            .overlay {
                Circle().strokeBorder(
                    LinearGradient(
                        colors: [Color.white.opacity(0.22), Color.white.opacity(0.02)],
                        startPoint: .top, endPoint: .bottom
                    ),
                    lineWidth: 1
                )
            }
        }
    }

    @ViewBuilder
    func glassCard(cornerRadius: CGFloat = 20, interactive: Bool = true, tint: Color? = nil) -> some View {
        if #available(macOS 26.0, *) {
            glassEffect(
                glass(interactive: interactive, tint: tint),
                in: .rect(cornerRadius: cornerRadius)
            )
        } else {
            background(
                .ultraThinMaterial,
                in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.10), lineWidth: 1)
            }
        }
    }

    /// Метка, по которой система понимает: это то же самое стекло, что было
    /// в другом месте экрана. Из неё и получается перетекание формы.
    @ViewBuilder
    func glassID(_ id: some Hashable & Sendable, in namespace: Namespace.ID) -> some View {
        if #available(macOS 26.0, *) {
            // Только метка. Перетекание формы — поведение по умолчанию для
            // одинаковых меток внутри ёмкости, а явный
            // glassEffectTransition вдобавок заставляет систему рисовать
            // содержимое через снимок, и текст на карточке замыливается.
            glassEffectID(id, in: namespace)
        } else {
            self
        }
    }
}

@available(macOS 26.0, *)
private func glass(interactive: Bool, tint: Color?) -> Glass {
    var value = Glass.regular
    if let tint { value = value.tint(tint) }
    return interactive ? value.interactive() : value
}

// MARK: - Кнопки

/// Нажатие и наведение курсором. На маке указатель есть всегда, и кнопка,
/// которая никак не отвечает на наведение, читается как неактивная.
struct PressableButtonStyle: ButtonStyle {
    var scale: CGFloat = 0.96
    @State private var hovering = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? scale : (hovering ? 1.02 : 1))
            .brightness(hovering && !configuration.isPressed ? 0.06 : 0)
            .animation(Theme.spring(0.18), value: configuration.isPressed)
            .animation(Theme.spring(0.18), value: hovering)
            .onHover { hovering = $0 }
    }
}

/// Круглая стеклянная кнопка.
///
/// Под курсором и при нажатии меняется не картинка, а размер самой
/// стеклянной формы: она пересобирается заново, поэтому блики и
/// преломление живут вместе с движением, а содержимое остаётся резким.
/// Масштабирование готового изображения дало бы мыло и ощущение наклейки.
struct GlassCircleButton<Content: View>: View {
    var size: CGFloat = 44
    var help: String?
    let action: () -> Void
    @ViewBuilder var content: () -> Content

    var body: some View {
        Button(action: action) {
            content()
        }
        .buttonStyle(GlassCircleButtonStyle(size: size))
        .help(help ?? "")
    }
}

struct GlassCircleButtonStyle: ButtonStyle {
    var size: CGFloat = 44

    func makeBody(configuration: Configuration) -> some View {
        Surface(configuration: configuration, size: size)
    }

    private struct Surface: View {
        let configuration: Configuration
        let size: CGFloat

        @State private var hovering = false
        @Environment(\.accessibilityReduceMotion) private var reduceMotion

        /// Наведение растягивает, нажатие поджимает. Слабое затухание даёт
        /// перелёт — из него и берётся ощущение упругой капли.
        private var scale: CGFloat {
            if reduceMotion { return 1 }
            if configuration.isPressed { return 0.86 }
            return hovering ? 1.12 : 1
        }

        var body: some View {
            configuration.label
                .frame(width: size * scale, height: size * scale)
                .glassCircle()
                // Место в раскладке фиксированное: соседи не должны
                // расползаться от того, что курсор задел кнопку.
                .frame(width: size * 1.12, height: size * 1.12)
                .contentShape(Circle())
                .onHover { hovering = $0 }
                .animation(.spring(response: 0.3, dampingFraction: 0.52), value: hovering)
                .animation(.spring(response: 0.24, dampingFraction: 0.5), value: configuration.isPressed)
        }
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    var cornerRadius: CGFloat = 14
    @State private var hovering = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(Theme.primaryGradient)
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(
                        LinearGradient(
                            colors: [Color.white.opacity(0.25), .clear],
                            startPoint: .top, endPoint: .center
                        ),
                        lineWidth: 1
                    )
            }
            .brightness(hovering && !configuration.isPressed ? 0.05 : 0)
            .shadow(color: Theme.accent.opacity(hovering ? 0.4 : 0.28), radius: hovering ? 16 : 12, y: 8)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(Theme.spring(0.18), value: configuration.isPressed)
            .animation(Theme.spring(0.18), value: hovering)
            .onHover { hovering = $0 }
    }
}

extension View {
    @ViewBuilder
    func glassCapsule(tint: Color? = nil) -> some View {
        if #available(macOS 26.0, *) {
            glassEffect(glass(interactive: true, tint: tint), in: .capsule)
        } else {
            background {
                Capsule().fill(tint ?? Color.white.opacity(0.12))
            }
            .overlay {
                Capsule().strokeBorder(Color.white.opacity(0.14), lineWidth: 1)
            }
        }
    }
}

// MARK: - Карточки

struct CardGroup: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(6)
            .background(Theme.card)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(alignment: .top) {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(
                        LinearGradient(
                            colors: [Color.white.opacity(0.06), .clear],
                            startPoint: .top, endPoint: .center
                        ),
                        lineWidth: 1
                    )
            }
    }
}

extension View {
    func cardGroup() -> some View { modifier(CardGroup()) }
}

struct CardDivider: View {
    var body: some View {
        Rectangle()
            .fill(Theme.divider)
            .frame(height: 1)
            .padding(.horizontal, 10)
    }
}

struct FlagChip: View {
    let flag: String
    var size: CGFloat = 36

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
            .fill(Theme.accentTint12)
            .frame(width: size, height: size)
            .overlay {
                Text(flag).font(.system(size: size * 0.5))
            }
    }
}

struct ProtocolBadge: View {
    var body: some View {
        Text("AWG2")
            .font(.manrope(10, .bold))
            .kerning(0.5)
            .foregroundColor(Theme.accentSoft)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Theme.accentTint12)
            .clipShape(RoundedRectangle(cornerRadius: 5, style: .continuous))
    }
}

// MARK: - Появление

struct FadeUp: ViewModifier {
    let delay: Double
    @State private var shown = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : (reduceMotion ? 0 : 12))
            .onAppear {
                withAnimation(.easeOut(duration: reduceMotion ? 0.01 : 0.45).delay(delay)) {
                    shown = true
                }
            }
    }
}

extension View {
    func fadeUp(delay: Double = 0) -> some View { modifier(FadeUp(delay: delay)) }
}

// MARK: - Поля ввода

/// Поле ввода в стиле приложения: системное оформление на тёмном фоне
/// выглядит инородно, а фокус с клавиатуры показывать обязательно.
struct FieldBox<Content: View>: View {
    var focused: Bool
    var invalid: Bool = false
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .textFieldStyle(.plain)
            .manrope(14, .medium)
            .foregroundColor(Theme.text)
            .padding(.horizontal, 14)
            .frame(height: 44)
            .background(Color.white.opacity(0.05))
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(borderColor, lineWidth: focused || invalid ? 1.5 : 1)
            }
            .animation(Theme.spring(0.18), value: focused)
            .animation(Theme.spring(0.18), value: invalid)
    }

    private var borderColor: Color {
        if invalid { return Theme.danger.opacity(0.8) }
        return focused ? Theme.accent.opacity(0.75) : Color.white.opacity(0.08)
    }
}
