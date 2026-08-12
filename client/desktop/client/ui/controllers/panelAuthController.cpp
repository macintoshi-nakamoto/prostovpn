#include "panelAuthController.h"

#include <QJsonDocument>
#include <QJsonParseError>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUrl>

#include <QDebug>

#include "core/utils/constants.h"
#include "core/utils/errorCodes.h"

namespace
{
    // Ключи в защищённом хранилище приложения.
    constexpr char kTokenKey[] = "Panel/token";
    constexpr char kLoginKey[] = "Panel/login";
    constexpr char kNameKey[] = "Panel/name";
    constexpr char kPublicIdKey[] = "Panel/publicId";
    constexpr char kUrlKey[] = "Panel/url";

    // Адрес панели по умолчанию. Собирая свою сборку, задайте свой через
    // -DPROSTO_PANEL_URL="https://panel.example.com".
#ifndef PROSTO_PANEL_URL
    #define PROSTO_PANEL_URL "http://127.0.0.1:8000"
#endif

    constexpr int kRequestTimeoutMs = 15000;
    // Раз в пять минут спрашиваем панель: не добавили ли страну, не кончилась
    // ли подписка. Чаще незачем, реже — человек слишком долго видит старое.
    constexpr int kRefreshIntervalMs = 5 * 60 * 1000;

    QString formatBytes(qint64 value)
    {
        constexpr qint64 kb = 1024;
        constexpr qint64 mb = kb * 1024;
        constexpr qint64 gb = mb * 1024;
        if (value <= 0)
            return QStringLiteral("0 ГБ");
        if (value < mb)
            return QStringLiteral("%1 КБ").arg(value / kb);
        if (value < gb)
            return QStringLiteral("%1 МБ").arg(value / mb);
        return QStringLiteral("%1 ГБ").arg(QString::number(double(value) / double(gb), 'f', 1));
    }
}

PanelAuthController::PanelAuthController(ImportController *importController, SecureQSettings *settings,
                                         QNetworkAccessManager *networkManager, QObject *parent)
    : QObject(parent),
      m_importController(importController),
      m_settings(settings),
      m_networkManager(networkManager)
{
    m_refreshTimer.setInterval(kRefreshIntervalMs);
    connect(&m_refreshTimer, &QTimer::timeout, this, &PanelAuthController::refresh);
}

// --- свойства ---------------------------------------------------------------

bool PanelAuthController::isLoggedIn() const
{
    return !m_token.isEmpty();
}

bool PanelAuthController::busy() const
{
    return m_busy;
}

QString PanelAuthController::errorString() const
{
    return m_error;
}

QString PanelAuthController::accountLogin() const
{
    return m_login;
}

QString PanelAuthController::accountName() const
{
    return m_name.isEmpty() ? m_login : m_name;
}

QString PanelAuthController::accountPublicId() const
{
    return m_publicId;
}

bool PanelAuthController::subscriptionActive() const
{
    return m_subscriptionActive;
}

QString PanelAuthController::subscriptionPlan() const
{
    return m_subscriptionPlan;
}

int PanelAuthController::subscriptionDaysLeft() const
{
    return m_subscriptionDaysLeft;
}

QString PanelAuthController::trafficUsedText() const
{
    return formatBytes(m_trafficUsed);
}

QString PanelAuthController::trafficLimitText() const
{
    return m_trafficLimit < 0 ? QStringLiteral("Безлимит") : formatBytes(m_trafficLimit);
}

double PanelAuthController::trafficRatio() const
{
    if (m_trafficLimit <= 0)
        return 0.0;
    return qBound(0.0, double(m_trafficUsed) / double(m_trafficLimit), 1.0);
}

QString PanelAuthController::panelUrl() const
{
    const QString stored = m_settings ? m_settings->value(kUrlKey).toString() : QString();
    return stored.isEmpty() ? QString::fromLatin1(PROSTO_PANEL_URL) : stored;
}

void PanelAuthController::setPanelUrl(const QString &url)
{
    if (!m_settings || url == panelUrl())
        return;
    m_settings->setValue(kUrlKey, url.trimmed());
    emit panelUrlChanged();
}

// --- вход -------------------------------------------------------------------

QNetworkRequest PanelAuthController::buildRequest(const QString &path, bool withToken) const
{
    QUrl url(panelUrl());
    url.setPath(path);

    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
    request.setTransferTimeout(kRequestTimeoutMs);
    if (withToken && !m_token.isEmpty())
        request.setRawHeader("Authorization", QByteArray("Bearer ") + m_token.toUtf8());
    return request;
}

QString PanelAuthController::humanError(int httpStatus, const QJsonObject &body, const QString &fallback)
{
    // Панель присылает понятный текст в detail — показываем его как есть,
    // он написан для человека, а не для лога.
    const QString detail = body.value(QStringLiteral("detail")).toString();
    if (!detail.isEmpty())
        return detail;
    if (httpStatus == 401)
        return QObject::tr("Неверный логин или пароль");
    if (httpStatus >= 500)
        return QObject::tr("Сервис временно недоступен");
    return fallback;
}

void PanelAuthController::login(const QString &login, const QString &password)
{
    if (m_busy)
        return;
    if (login.trimmed().isEmpty() || password.isEmpty()) {
        setError(tr("Введите логин и пароль"));
        emit loginFailed(m_error);
        return;
    }

    setBusy(true);
    setError({});

    QJsonObject payload;
    payload[QStringLiteral("login")] = login.trimmed();
    payload[QStringLiteral("password")] = password;
    // Платформу берём из общей константы: панель показывает её в списке
    // сессий, и «windows» с телефона там сбивал бы с толку.
    payload[QStringLiteral("platform")] = QString::fromLatin1(Constants::PLATFORM_NAME);
    payload[QStringLiteral("app_version")] = QString(APP_VERSION);

    QNetworkReply *reply = m_networkManager->post(buildRequest(QStringLiteral("/api/v1/login"), false),
                                                  QJsonDocument(payload).toJson(QJsonDocument::Compact));

    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();
        setBusy(false);

        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        const QByteArray raw = reply->readAll();

        QJsonParseError parseError {};
        const QJsonObject body = QJsonDocument::fromJson(raw, &parseError).object();

        if (reply->error() != QNetworkReply::NoError || status != 200) {
            // Сеть могла не дойти до панели вовсе — тогда JSON пустой и в
            // сообщении должно быть про соединение, а не про пароль.
            const QString fallback =
                    status == 0 ? tr("Не удалось связаться с сервисом") : tr("Не удалось войти");
            const QString message = humanError(status, body, fallback);
            setError(message);
            emit loginFailed(message);
            return;
        }

        applyLoginResponse(body);
        emit loginSucceeded();
    });
}

void PanelAuthController::applyLoginResponse(const QJsonObject &body)
{
    m_token = body.value(QStringLiteral("token")).toString();

    const QJsonObject account = body.value(QStringLiteral("account")).toObject();
    m_login = account.value(QStringLiteral("login")).toString();
    m_name = account.value(QStringLiteral("name")).toString();
    m_publicId = account.value(QStringLiteral("public_id")).toString();

    if (m_settings) {
        m_settings->setValue(kTokenKey, m_token);
        m_settings->setValue(kLoginKey, m_login);
        m_settings->setValue(kNameKey, m_name);
        m_settings->setValue(kPublicIdKey, m_publicId);
    }

    applySubscription(body.value(QStringLiteral("subscription")).toObject());
    const int imported = importServers(body.value(QStringLiteral("servers")).toArray());

    emit sessionChanged();
    emit serversUpdated(imported);
    m_refreshTimer.start();
}

void PanelAuthController::applySubscription(const QJsonObject &subscription)
{
    m_subscriptionActive = subscription.value(QStringLiteral("active")).toBool();
    m_subscriptionPlan = subscription.value(QStringLiteral("plan")).toString();
    m_subscriptionDaysLeft = subscription.value(QStringLiteral("days_left")).toInt();
    m_trafficUsed = qint64(subscription.value(QStringLiteral("traffic_used_bytes")).toDouble());

    const QJsonValue limit = subscription.value(QStringLiteral("traffic_limit_bytes"));
    // null в ответе — безлимит. Отдельного флага панель не присылает:
    // отсутствие лимита и есть безлимит.
    m_trafficLimit = limit.isNull() || limit.isUndefined() ? -1 : qint64(limit.toDouble());
}

int PanelAuthController::importServers(const QJsonArray &servers)
{
    if (!m_importController)
        return 0;

    int imported = 0;
    for (const QJsonValue &value : servers) {
        const QJsonObject server = value.toObject();
        const QString config = server.value(QStringLiteral("config")).toString();
        if (config.isEmpty())
            continue;

        ImportController::ImportResult result = m_importController->extractConfigFromData(config);
        if (result.errorCode != amnezia::ErrorCode::NoError) {
            qWarning() << "panel: config from server cannot be parsed, error" << int(result.errorCode);
            continue;
        }

        // Имя сервера — страна и город. Ни адреса, ни ключа в интерфейсе
        // быть не должно: человек выбирает страну, остальное его не касается.
        const QString country = server.value(QStringLiteral("country")).toString();
        const QString city = server.value(QStringLiteral("city")).toString();
        QString title = country.isEmpty() ? server.value(QStringLiteral("name")).toString() : country;
        if (!city.isEmpty())
            title += QStringLiteral(", ") + city;

        QJsonObject config_ = result.config;
        config_[QStringLiteral("description")] = title;
        config_[QStringLiteral("name")] = title;

        m_importController->importConfig(config_);
        ++imported;
    }
    return imported;
}

// --- обновление и выход -----------------------------------------------------

void PanelAuthController::refresh()
{
    if (m_token.isEmpty() || m_busy)
        return;

    QNetworkReply *reply = m_networkManager->get(buildRequest(QStringLiteral("/api/v1/servers"), true));

    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();

        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        if (status == 401) {
            // Токен отозвали в панели — доступ закончился, просим войти снова.
            logout();
            return;
        }
        if (reply->error() != QNetworkReply::NoError || status != 200)
            return;

        const QJsonObject body = QJsonDocument::fromJson(reply->readAll()).object();
        applySubscription(body.value(QStringLiteral("subscription")).toObject());
        const int imported = importServers(body.value(QStringLiteral("servers")).toArray());
        emit sessionChanged();
        emit serversUpdated(imported);
    });
}

bool PanelAuthController::restoreSession()
{
    if (!m_settings)
        return false;

    m_token = m_settings->value(kTokenKey).toString();
    m_login = m_settings->value(kLoginKey).toString();
    m_name = m_settings->value(kNameKey).toString();
    m_publicId = m_settings->value(kPublicIdKey).toString();

    if (m_token.isEmpty())
        return false;

    emit sessionChanged();
    // Сразу спрашиваем панель: подписка могла кончиться, пока приложение
    // было закрыто, и показывать старый список стран нельзя.
    refresh();
    m_refreshTimer.start();
    return true;
}

void PanelAuthController::logout()
{
    m_refreshTimer.stop();

    if (!m_token.isEmpty()) {
        // Гасим сессию и на стороне панели — иначе она останется висеть
        // в списке устройств администратора.
        QNetworkReply *reply = m_networkManager->post(buildRequest(QStringLiteral("/api/v1/logout"), true), QByteArray("{}"));
        connect(reply, &QNetworkReply::finished, reply, &QNetworkReply::deleteLater);
    }

    m_token.clear();
    m_login.clear();
    m_name.clear();
    m_publicId.clear();
    m_subscriptionActive = false;
    m_subscriptionPlan.clear();
    m_subscriptionDaysLeft = 0;
    m_trafficUsed = 0;
    m_trafficLimit = -1;

    if (m_settings) {
        m_settings->remove(kTokenKey);
        m_settings->remove(kLoginKey);
        m_settings->remove(kNameKey);
        m_settings->remove(kPublicIdKey);
    }

    emit sessionChanged();
    emit loggedOut();
}

// --- служебное --------------------------------------------------------------

void PanelAuthController::setBusy(bool value)
{
    if (m_busy == value)
        return;
    m_busy = value;
    emit busyChanged();
}

void PanelAuthController::setError(const QString &message)
{
    if (m_error == message)
        return;
    m_error = message;
    emit errorChanged();
}
