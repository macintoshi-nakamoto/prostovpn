#include "appUpdateController.h"

#include <QDebug>
#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QStandardPaths>
#include <QUrl>
#include <QUrlQuery>

#include "core/utils/constants.h"

namespace
{
    constexpr int kRequestTimeoutMs = 15000;
}

AppUpdateController::AppUpdateController(QNetworkAccessManager *networkManager, QObject *parent)
    : QObject(parent), m_networkManager(networkManager)
{
}

QString AppUpdateController::currentVersion() const
{
    return QString(APP_VERSION);
}

// --- проверка ---------------------------------------------------------------

void AppUpdateController::check()
{
    if (m_panelUrl.isEmpty() || m_busy)
        return;

    QUrl url(m_panelUrl);
    url.setPath(QStringLiteral("/api/v1/version"));

    QUrlQuery query;
    query.addQueryItem(QStringLiteral("platform"), QString::fromLatin1(Constants::PLATFORM_NAME));
    query.addQueryItem(QStringLiteral("current"), currentVersion());
    url.setQuery(query);

    QNetworkRequest request(url);
    request.setTransferTimeout(kRequestTimeoutMs);

    QNetworkReply *reply = m_networkManager->get(request);
    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();

        // Проверка версии — фоновая: если сеть недоступна, человеку об этом
        // сообщать нечего, он не просил проверять.
        if (reply->error() != QNetworkReply::NoError)
            return;

        const QJsonObject body = QJsonDocument::fromJson(reply->readAll()).object();
        m_updateAvailable = body.value(QStringLiteral("update_available")).toBool();
        m_mandatory = body.value(QStringLiteral("mandatory")).toBool();
        m_latestVersion = body.value(QStringLiteral("version")).toString();
        m_changelog = body.value(QStringLiteral("changelog")).toString();
        m_downloadUrl = body.value(QStringLiteral("url")).toString();

        emit updateChanged();
        if (m_updateAvailable)
            emit updateFound(m_latestVersion);
    });
}

// --- скачивание и установка -------------------------------------------------

void AppUpdateController::downloadAndInstall()
{
    if (m_busy)
        return;
    if (m_downloadUrl.isEmpty()) {
        setError(tr("Ссылка на обновление не пришла — попробуйте позже"));
        return;
    }

    setBusy(true);
    setError({});
    setProgress(0);

    QNetworkRequest request{QUrl(m_downloadUrl)};
    // Таймаут передачи здесь не ставим: установщик весит десятки мегабайт,
    // и на медленной сети это не ошибка, а норма.
    request.setAttribute(QNetworkRequest::RedirectPolicyAttribute,
                         QNetworkRequest::NoLessSafeRedirectPolicy);

    QNetworkReply *reply = m_networkManager->get(request);

    connect(reply, &QNetworkReply::downloadProgress, this, [this](qint64 got, qint64 total) {
        if (total > 0)
            setProgress(int(got * 100 / total));
    });

    connect(reply, &QNetworkReply::finished, this, [this, reply]() {
        reply->deleteLater();
        setBusy(false);

        if (reply->error() != QNetworkReply::NoError) {
            setError(tr("Не удалось скачать обновление: %1").arg(reply->errorString()));
            return;
        }

        // Имя берём из адреса: по расширению система понимает, чем открыть
        // файл — msi, dmg, apk или AppImage.
        QString fileName = QFileInfo(QUrl(m_downloadUrl).path()).fileName();
        if (fileName.isEmpty())
            fileName = QStringLiteral("prosto-vpn-update");

        const QString dir = QStandardPaths::writableLocation(QStandardPaths::TempLocation);
        const QString path = QDir(dir).filePath(fileName);

        QFile file(path);
        if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
            setError(tr("Некуда сохранить обновление: %1").arg(file.errorString()));
            return;
        }
        file.write(reply->readAll());
        file.close();

        emit downloadFinished(path);

        if (!launchInstaller(path))
            setError(tr("Обновление скачано в %1 — запустите его вручную").arg(path));
    });
}

bool AppUpdateController::launchInstaller(const QString &path)
{
    // Открываем средствами системы, а не своим запуском процесса: установщик
    // ставится поверх и обновляет приложение на месте, поэтому настройки и
    // вход сохраняются, а переустанавливать вручную ничего не нужно.
    const bool opened = QDesktopServices::openUrl(QUrl::fromLocalFile(path));
    if (!opened)
        qWarning() << "не удалось открыть установщик" << path;
    return opened;
}

// --- служебное --------------------------------------------------------------

void AppUpdateController::setBusy(bool value)
{
    if (m_busy == value)
        return;
    m_busy = value;
    emit busyChanged();
}

void AppUpdateController::setError(const QString &message)
{
    if (m_error == message)
        return;
    m_error = message;
    emit errorChanged();
}

void AppUpdateController::setProgress(int value)
{
    if (m_progress == value)
        return;
    m_progress = value;
    emit progressChanged();
}
