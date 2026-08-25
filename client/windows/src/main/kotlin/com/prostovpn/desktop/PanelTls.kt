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

    fun apply(connection: java.net.URLConnection) {
        if (connection !is HttpsURLConnection) return
        val factory = socketFactory ?: return
        val ourCert = pinned ?: return
        connection.sslSocketFactory = factory

        val panelHost = runCatching { URL(PanelApi.baseUrl).host }.getOrNull()
        connection.setHostnameVerifier { hostname, session ->

            if (HttpsURLConnection.getDefaultHostnameVerifier().verify(hostname, session)) {
                return@setHostnameVerifier true
            }

            if (panelHost == null || hostname != panelHost) return@setHostnameVerifier false
            val presented = runCatching { session.peerCertificates.firstOrNull() }.getOrNull()
            presented is X509Certificate && presented == ourCert
        }
    }
}
