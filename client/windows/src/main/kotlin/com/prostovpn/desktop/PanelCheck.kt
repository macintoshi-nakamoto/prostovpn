package com.prostovpn.desktop

import kotlinx.coroutines.runBlocking

object PanelCheck {
    @JvmStatic
    fun main(args: Array<String>) {
        val url = args.getOrNull(0) ?: PanelApi.baseUrl
        val login = args.getOrNull(1).orEmpty()
        val password = args.getOrNull(2).orEmpty()

        PanelApi.baseUrl = url
        println("панель: $url")

        if (login.isEmpty() || password.isEmpty()) {
            println("ОШИБКА: нужны логин и пароль")
            return
        }

        runBlocking {
            PanelApi.login(login, password)
                .onSuccess { session ->
                    println("вход выполнен")
                    println("  аккаунт:   ${session.name ?: session.login} (${session.publicId})")
                    println("  подписка:  " + if (session.subscriptionActive) "активна, дней ${session.daysLeft}" else "нет")
                    val limit = session.trafficLimitBytes
                    println("  трафик:    ${session.trafficUsedBytes / 1024 / 1024} МБ из " +
                            if (limit == null) "безлимита" else "${limit / 1024 / 1024} МБ")
                    println("  стран:     ${session.servers.size}")
                    session.servers.forEach { server ->
                        val leaks = listOfNotNull(
                            "host".takeIf { server.host.isNotEmpty() },
                        )
                        println("    - ${server.country}, ${server.city} (${server.countryCode})" +
                                "  конфиг: ${server.config?.length ?: 0} символов" +
                                if (leaks.isEmpty()) "  утечек нет" else "  УТЕЧКА: $leaks")
                    }

                    PanelApi.servers(session.token)
                        .onSuccess { println("  повторный запрос по токену: стран ${it.servers.size}") }
                        .onFailure { println("  повторный запрос не удался: ${it.message}") }

                    PanelApi.logout(session.token)
                    println("  выход выполнен")
                }
                .onFailure { error ->
                    println("вход не выполнен: ${error.message}")
                }
        }
    }
}
