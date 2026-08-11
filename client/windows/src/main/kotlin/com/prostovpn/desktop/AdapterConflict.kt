package com.prostovpn.desktop

import java.net.NetworkInterface

/**
 * Проверка, не занят ли адрес туннеля другим работающим VPN.
 *
 * Ключ Amnezia задаёт клиенту фиксированный адрес (`Address = 10.8.1.3/32`).
 * Если тем же ключом уже поднят другой клиент — например, официальный
 * AmneziaVPN, — этот адрес висит на его адаптере. Windows не отдаёт адрес
 * двум интерфейсам сразу: `SetIPAddressesForFamily` возвращает
 * `ERROR_OBJECT_ALREADY_EXISTS`, служба туннеля падает, и в журнал системы
 * попадает лишь «The object already exists».
 *
 * Освободить адрес сами мы не можем и не должны: он принадлежит чужому
 * живому соединению. Поэтому ловим конфликт заранее — до запроса прав
 * администратора — и называем виновника по имени.
 */
object AdapterConflict {

    /**
     * Имя адаптера, который уже держит адрес из конфига, или null.
     *
     * Свои адаптеры пропускаем: остаток прошлого подключения снимает сама
     * служба при установке, и принимать его за чужой VPN нельзя.
     */
    fun holderOf(configText: String): String? {
        val wanted = addressesOf(configText)
        if (wanted.isEmpty()) return null

        val interfaces = runCatching { NetworkInterface.getNetworkInterfaces() }.getOrNull()
            ?: return null

        for (nif in interfaces) {
            val name = nif.displayName ?: nif.name ?: continue
            if (isOurs(name) || isOurs(nif.name.orEmpty())) continue
            if (!runCatching { nif.isUp }.getOrDefault(false)) continue

            for (address in nif.inetAddresses) {
                // У IPv6 адрес приходит с зоной («fe80::1%12») — она не часть адреса
                val text = address.hostAddress?.substringBefore('%') ?: continue
                if (text in wanted) return name
            }
        }
        return null
    }

    /** Адреса из строки `Address` секции `[Interface]`, без масок. */
    private fun addressesOf(configText: String): Set<String> {
        var section = ""
        for (rawLine in configText.lineSequence()) {
            val line = rawLine.substringBefore('#').trim()
            if (line.isEmpty()) continue
            if (line.startsWith("[") && line.endsWith("]")) {
                section = line.trim('[', ']').lowercase()
                continue
            }
            if (section != "interface") continue
            val key = line.substringBefore('=', "").trim()
            if (!key.equals("address", ignoreCase = true)) continue
            return line.substringAfter('=')
                .split(',')
                .map { it.trim().substringBefore('/') }
                .filter { it.isNotEmpty() }
                .toSet()
        }
        return emptySet()
    }

    private fun isOurs(name: String): Boolean =
        name.contains(WindowsTunnel.TUNNEL_NAME, ignoreCase = true)
}
