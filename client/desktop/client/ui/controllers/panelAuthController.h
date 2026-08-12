#ifndef PANELAUTHCONTROLLER_H
#define PANELAUTHCONTROLLER_H

#include <QJsonArray>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QObject>
#include <QTimer>

#include "core/controllers/selfhosted/importController.h"
#include "secureQSettings.h"

/**
 * Вход в приложение по логину и паролю, выданным в панели.
 *
 * Панель отдаёт список доступных стран вместе с готовыми конфигами. Конфиг
 * уходит прямо в импорт и дальше в туннель — на экране он не появляется
 * никогда: человек выбирает страну, а не адрес сервера.
 *
 * Токен и учётные данные лежат в SecureQSettings, как и остальные секреты
 * приложения: в открытом виде на диске не остаётся ничего.
 */
class PanelAuthController : public QObject
{
    Q_OBJECT

    Q_PROPERTY(bool isLoggedIn READ isLoggedIn NOTIFY sessionChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(QString errorString READ errorString NOTIFY errorChanged)
    Q_PROPERTY(QString accountLogin READ accountLogin NOTIFY sessionChanged)
    Q_PROPERTY(QString accountName READ accountName NOTIFY sessionChanged)
    Q_PROPERTY(QString accountPublicId READ accountPublicId NOTIFY sessionChanged)
    Q_PROPERTY(bool subscriptionActive READ subscriptionActive NOTIFY sessionChanged)
    Q_PROPERTY(QString subscriptionPlan READ subscriptionPlan NOTIFY sessionChanged)
    Q_PROPERTY(int subscriptionDaysLeft READ subscriptionDaysLeft NOTIFY sessionChanged)
    Q_PROPERTY(QString trafficUsedText READ trafficUsedText NOTIFY sessionChanged)
    Q_PROPERTY(QString trafficLimitText READ trafficLimitText NOTIFY sessionChanged)
    Q_PROPERTY(double trafficRatio READ trafficRatio NOTIFY sessionChanged)
    Q_PROPERTY(QString panelUrl READ panelUrl WRITE setPanelUrl NOTIFY panelUrlChanged)

public:
    explicit PanelAuthController(ImportController *importController, SecureQSettings *settings,
                                 QNetworkAccessManager *networkManager, QObject *parent = nullptr);

    bool isLoggedIn() const;
    bool busy() const;
    QString errorString() const;
    QString accountLogin() const;
    QString accountName() const;
    QString accountPublicId() const;
    bool subscriptionActive() const;
    QString subscriptionPlan() const;
    int subscriptionDaysLeft() const;
    QString trafficUsedText() const;
    QString trafficLimitText() const;
    double trafficRatio() const;
    QString panelUrl() const;
    void setPanelUrl(const QString &url);

public slots:
    void login(const QString &login, const QString &password);
    /** Тихо обновляет список стран по сохранённому токену. */
    void refresh();
    void logout();
    /** Есть ли сохранённая сессия — решает, показывать ли экран входа. */
    bool restoreSession();

signals:
    void sessionChanged();
    void busyChanged();
    void errorChanged();
    void panelUrlChanged();

    void loginSucceeded();
    void loginFailed(const QString &message);
    /** Страны приехали и разложены по серверам приложения. */
    void serversUpdated(int count);
    void loggedOut();

private:
    void applyLoginResponse(const QJsonObject &body);
    void applySubscription(const QJsonObject &subscription);
    int importServers(const QJsonArray &servers);
    void setBusy(bool value);
    void setError(const QString &message);
    QNetworkRequest buildRequest(const QString &path, bool withToken) const;
    /** Читаемая ошибка вместо кода: её видит человек на экране входа. */
    static QString humanError(int httpStatus, const QJsonObject &body, const QString &fallback);

    ImportController *m_importController {};
    SecureQSettings *m_settings {};
    QNetworkAccessManager *m_networkManager {};

    QString m_token;
    QString m_login;
    QString m_name;
    QString m_publicId;

    bool m_subscriptionActive = false;
    QString m_subscriptionPlan;
    int m_subscriptionDaysLeft = 0;
    qint64 m_trafficUsed = 0;
    qint64 m_trafficLimit = -1; // -1 — безлимит

    bool m_busy = false;
    QString m_error;

    // Периодическое обновление: панель могла добавить страну или закрыть
    // доступ, и приложение должно узнать об этом само.
    QTimer m_refreshTimer;
};

#endif // PANELAUTHCONTROLLER_H
