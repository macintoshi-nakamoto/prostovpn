import SwiftUI

/*
 Стекло, которое не роняет кадры.

 Правило, из которого всё остальное следует: РАЗМЫТИЕ И ДВИЖЕНИЕ НЕ ЖИВУТ
 НА ОДНОМ СЛОЕ. Материал (`.ultraThinMaterial`, `.glassEffect`) — это
 размытие того, что под ним. Пока слой стоит на месте, система размывает
 фон один раз и переиспользует результат. Стоит тот же слой начать двигать,
 масштабировать или менять ему прозрачность — область размытия меняется
 каждый кадр, и весь фон под ней пересчитывается заново, шестьдесят раз в
 секунду.

 Ровно на этом лагала веб-панель: подложка с blur(9px) размывала таблицу на
 сотню строк, пока шторка выезжала. И ровно это происходит здесь, если
 повесить `.ultraThinMaterial` на карточку, которая появляется анимацией.

 Отсюда три приёма, которыми пользуется весь интерфейс:

 1. Стекло — статичная подложка. Двигается СОДЕРЖИМОЕ поверх него, а не
    само стекло (см. GlassCard: анимация уходит на внутренний слой).
 2. Что анимируется постоянно — рисуется в Canvas и не трогает раскладку
    (см. GlowPulse, кольцо подключения).
 3. Тяжёлые статичные композиции схлопываются в один слой через
    `drawingGroup()`: система рисует их один раз в текстуру, дальше двигает
    готовую картинку.
 */

// MARK: - Стеклянная карточка

/// Подложка «жидкого стекла» с честным поведением на всех версиях iOS.
///
/// На iOS 26+ берёт системный `.glassEffect` — он аппаратный и заметно
/// дешевле ручного материала. Ниже — материал с тонкой светлой каймой,
/// которая и создаёт ощущение стекла: без неё поверхность читается просто
/// как полупрозрачная заливка.
struct GlassCard<Content: View>: View {
    var cornerRadius: CGFloat = 22
    /// Интерактивная карточка слегка отзывается на нажатие.
    var interactive: Bool = false
    @ViewBuilder var content: () -> Content

    var body: some View {
        content()
            .background {
                GlassBackground(cornerRadius: cornerRadius, interactive: interactive)
            }
    }
}

/// Сама подложка. Вынесена отдельно, чтобы её можно было поставить фоном
/// чему угодно, не заворачивая содержимое.
struct GlassBackground: View {
    var cornerRadius: CGFloat = 22
    var interactive: Bool = false

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)

        if #available(iOS 26.0, *), interactive {
            shape.fill(.clear).glassEffect(.regular.interactive(), in: shape)
        } else if #available(iOS 26.0, *) {
            shape.fill(.clear).glassEffect(.regular, in: shape)
        } else {
            ZStack {
                shape.fill(.ultraThinMaterial)
                // Заливка поверх материала: чистый материал на тёмном фоне
                // уходит в серый, а бренд у нас тёплый.
                shape.fill(Color.white.opacity(0.045))
                // Кайма-блик сверху — то, что делает поверхность стеклом.
                shape.strokeBorder(
                    LinearGradient(
                        colors: [Color.white.opacity(0.14), Color.white.opacity(0.02)],
                        startPoint: .top,
                        endPoint: .bottom
                    ),
                    lineWidth: 1
                )
            }
            // Схлопываем три слоя в один: дальше система двигает готовую
            // текстуру вместо того, чтобы каждый кадр складывать материал,
            // заливку и обводку заново.
            .compositingGroup()
        }
    }
}

// MARK: - Появление без пересчёта размытия

/// Появление содержимого над неподвижным стеклом.
///
/// Анимируется только то, что лежит НА стекле. Само стекло стоит на месте,
/// поэтому область размытия не меняется и фон не пересчитывается. Именно
/// так карточка выезжает плавно даже на iPhone позапрошлого поколения.
struct GlassReveal<Content: View>: View {
    var delay: Double = 0
    @ViewBuilder var content: () -> Content

    @State private var shown = false

    var body: some View {
        content()
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : 14)
            .animation(.spring(response: 0.42, dampingFraction: 0.86).delay(delay), value: shown)
            .onAppear { shown = true }
            // Уважаем системную настройку «уменьшить движение»: она стоит у
            // людей, которым от анимаций физически плохо.
            .transaction { transaction in
                if UIAccessibility.isReduceMotionEnabled {
                    transaction.animation = nil
                }
            }
    }
}

// MARK: - Постоянные анимации

/// Пульсирующее свечение под кнопкой подключения.
///
/// Canvas, а не набор View с `.animation`: свечение перерисовывается
/// каждый кадр, и через View это означало бы пересчёт раскладки шестьдесят
/// раз в секунду. Canvas рисует в один слой и раскладку не трогает вовсе.
struct GlowPulse: View {
    var color: Color
    var isActive: Bool

    var body: some View {
        TimelineView(.animation(paused: !isActive)) { context in
            Canvas { ctx, size in
                guard isActive else { return }
                let t = context.date.timeIntervalSinceReferenceDate
                // Медленное дыхание: период около трёх секунд, амплитуда
                // небольшая — свечение должно жить, а не мигать.
                let wave = (sin(t * 2.0) + 1) / 2
                let radius = size.width * (0.42 + 0.05 * wave)
                let opacity = 0.18 + 0.12 * wave

                let center = CGPoint(x: size.width / 2, y: size.height / 2)
                let gradient = Gradient(colors: [color.opacity(opacity), .clear])
                ctx.fill(
                    Circle().path(in: CGRect(
                        x: center.x - radius, y: center.y - radius,
                        width: radius * 2, height: radius * 2
                    )),
                    with: .radialGradient(
                        gradient,
                        center: center,
                        startRadius: radius * 0.25,
                        endRadius: radius
                    )
                )
            }
        }
        .allowsHitTesting(false)
        // Свечение декоративное: озвучивать его нечего.
        .accessibilityHidden(true)
    }
}

/// Кольцо ожидания вокруг кнопки подключения.
///
/// Тоже Canvas и тоже с паузой: остановленный TimelineView не будит
/// отрисовку вовсе, а значит подключённое приложение не тратит батарею на
/// кольцо, которого не видно.
struct ProgressRing: View {
    var color: Color
    var isActive: Bool
    var lineWidth: CGFloat = 2.5

    var body: some View {
        TimelineView(.animation(paused: !isActive)) { context in
            Canvas { ctx, size in
                guard isActive else { return }
                let angle = context.date.timeIntervalSinceReferenceDate
                    .truncatingRemainder(dividingBy: 1.1) / 1.1

                let inset = lineWidth / 2
                let rect = CGRect(origin: .zero, size: size).insetBy(dx: inset, dy: inset)
                let path = Circle().path(in: rect)

                ctx.stroke(
                    path,
                    with: .conicGradient(
                        Gradient(stops: [
                            .init(color: .clear, location: 0),
                            .init(color: color.opacity(0.15), location: 0.55),
                            .init(color: color, location: 1),
                        ]),
                        center: CGPoint(x: size.width / 2, y: size.height / 2),
                        angle: .degrees(angle * 360)
                    ),
                    style: StrokeStyle(lineWidth: lineWidth, lineCap: .round)
                )
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

// MARK: - Нажатие

/// Отклик на нажатие: сжатие без анимации размытия.
///
/// Масштабируется содержимое кнопки, а не стеклянная подложка под ним, —
/// иначе каждое касание пересчитывало бы размытие.
struct PressableStyle: ButtonStyle {
    var scale: CGFloat = 0.97

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? scale : 1)
            .animation(.spring(response: 0.22, dampingFraction: 0.7), value: configuration.isPressed)
    }
}

extension View {
    /// Схлопывает поддерево в одну текстуру.
    ///
    /// Для статичных композиций из нескольких слоёв — градиент, обводка,
    /// тень. Двигать одну картинку дешевле, чем складывать слои каждый
    /// кадр. НЕ применять к тому, что часто меняет содержимое: тогда
    /// текстура пересоздаётся, и выходит дороже.
    func flattenLayer() -> some View {
        drawingGroup()
    }
}
