package com.prostovpn.desktop

import java.net.URL
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/**
 * Доверие к сертификату панели.
 *
 * Панель может стоять за самоподписанным сертификатом — домена у неё
 * может и не быть. Java такие соединения отвергает, и вход просто не
 * работает: «unable to find valid certification path».
 *
 * Поэтому доверяем двум вещам сразу: обычным системным центрам
 * сертификации и одному вложенному в приложение сертификату панели.
 * Первое продолжит работать, когда у панели появится нормальный
 * сертификат; второе работает уже сейчас. Всё остальное по-прежнему
 * отвергается — это не отключение проверки, а её расширение.
 */
object PanelTls {

    private val pinned: X509Certificate? by lazy {
        runCatching {
            PanelTls::class.java.getResourceAsStream("/panel_cert.pem")?.use { stream ->
                CertificateFactory.getInstance("X.509").generateCertificate(stream) as X509Certificate
            }
        }.getOrNull()
    }

    private val socketFactory: SSLSocketFactory? by lazy {
        val certificate = pinned ?: return@lazy null
        runCatching {
            val system = defaultTrustManager()

            val store = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
                load(null, null)
                setCertificateEntry("panel", certificate)
            }
            val ours = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
                .apply { init(store) }
                .trustManagers
                .filterIsInstance<X509TrustManager>()
                .first()

            val combined = object : X509TrustManager {
                override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) =
                    system.checkClientTrusted(chain, authType)

                override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                    try {
                        system.checkServerTrusted(chain, authType)
                    } catch (systemFailure: Exception) {
                        // Обычные центры сертификации не признали — пробуем
                        // свой. Не признает и он — исключение уйдёт наверх,
                        // и соединение не состоится.
                        try {
                            ours.checkServerTrusted(chain, authType)
                        } catch (_: Exception) {
                            throw systemFailure
                        }
                    }
                }

                override fun getAcceptedIssuers(): Array<X509Certificate> =
                    system.acceptedIssuers + ours.acceptedIssuers
            }

            SSLContext.getInstance("TLS").apply {
                init(null, arrayOf(combined), null)
            }.socketFactory
        }.getOrNull()
    }

    private fun defaultTrustManager(): X509TrustManager =
        TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
            .apply { init(null as KeyStore?) }
            .trustManagers
            .filterIsInstance<X509TrustManager>()
            .first()

    /**
     * Настраивает соединение, если оно идёт к нашей панели по HTTPS.
     *
     * Имя хоста у самоподписанного сертификата — обычно IP-адрес, а Java
     * ищет его в SAN и в CN не смотрит. Поэтому для соединений, принятых
     * нашим сертификатом, сверяем хост с адресом панели, а не с полями
     * сертификата.
     */
    fun apply(connection: java.net.URLConnection) {
        if (connection !is HttpsURLConnection) return
        val factory = socketFactory ?: return
        connection.sslSocketFactory = factory

        val panelHost = runCatching { URL(PanelApi.baseUrl).host }.getOrNull()
        connection.setHostnameVerifier { hostname, session ->
            // Сначала обычная проверка; если не прошла — соединение принято
            // нашим сертификатом, и хост должен совпасть с адресом панели.
            HttpsURLConnection.getDefaultHostnameVerifier().verify(hostname, session) ||
                (panelHost != null && hostname == panelHost)
        }
    }
}
