#ifndef APPUPDATECONTROLLER_H
#define APPUPDATECONTROLLER_H

#include <QNetworkAccessManager>
#include <QObject>

/**
 * Обновление приложения через нашу панель.
 *
 * Приложение спрашивает у панели, нет ли версии новее установленной, и,
 * если есть, показывает кнопку. Переустанавливать вручную не нужно:
 * установщик скачивается по ссылке из ответа и запускается поверх —
 * настройки и вход при этом сохраняются.
 *
 * Штатный UpdateController из AmneziaVPN здесь не подходит: он ходит в
 * их инфраструктуру, которой мы не управляем.
 */
class AppUpdateController : public QObject
{
    Q_OBJECT

    Q_PROPERTY(bool updateAvailable READ updateAvailable NOTIFY updateChanged)
    Q_PROPERTY(bool mandatory READ mandatory NOTIFY updateChanged)
    Q_PROPERTY(QString latestVersion READ latestVersion NOTIFY updateChanged)
    Q_PROPERTY(QString currentVersion READ currentVersion CONSTANT)
    Q_PROPERTY(QString changelog READ changelog NOTIFY updateChanged)
    Q_PROPERTY(QString errorString READ errorString NOTIFY errorChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
    Q_PROPERTY(int progress READ progress NOTIFY progressChanged)

public:
    explicit AppUpdateController(QNetworkAccessManager *networkManager, QObject *parent = nullptr);

    bool updateAvailable() const { return m_updateAvailable; }
    bool mandatory() const { return m_mandatory; }
    QString latestVersion() const { return m_latestVersion; }
    QString currentVersion() const;
    QString changelog() const { return m_changelog; }
    QString errorString() const { return m_error; }
    bool busy() const { return m_busy; }
    int progress() const { return m_progress; }

    /** Адрес панели задаёт PanelAuthController — он же владеет настройкой. */
    void setPanelUrl(const QString &url) { m_panelUrl = url; }

public slots:
    /** Спросить панель, есть ли версия новее. Молча, без ошибок на экране. */
    void check();
    /** Скачать установщик и запустить его. */
    void downloadAndInstall();

signals:
    void updateChanged();
    void errorChanged();
    void busyChanged();
    void progressChanged();
    void updateFound(const QString &version);
    void downloadFinished(const QString &path);

private:
    void setBusy(bool value);
    void setError(const QString &message);
    void setProgress(int value);
    /** Запускает скачанный файл средствами системы. */
    bool launchInstaller(const QString &path);

    QNetworkAccessManager *m_networkManager {};
    QString m_panelUrl;

    bool m_updateAvailable = false;
    bool m_mandatory = false;
    QString m_latestVersion;
    QString m_changelog;
    QString m_downloadUrl;

    bool m_busy = false;
    int m_progress = 0;
    QString m_error;
};

#endif // APPUPDATECONTROLLER_H
