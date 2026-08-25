package com.prostovpn.desktop

import java.io.File

fun main(args: Array<String>) {
    val path = args.firstOrNull() ?: error("укажите файл с ключом vpn://…")
    val key = File(path).readText().trim()

    val info = KeyParser.extractServer(key)
    println("host      = ${info?.host}")
    println("страна    = ${info?.country ?: "—"}")
    val config = info?.config
    if (config == null) {
        println("КОНФИГ НЕ ИЗВЛЁЧЁН")
        return
    }

    val sanitized = WgConfig.sanitize(SplitTunnel.applyToConfig(config, "0.0.0.0/0, ::/0"))
    if (sanitized == null) {
        println("САНИТАЙЗЕР ОТВЕРГ КОНФИГ")
        return
    }

    println("выброшено движком не поддерживается: ${WgConfig.unsupportedKeys(config).ifEmpty { listOf("—") }}")
    println("--- что уйдёт движку (секреты скрыты) ---")
    sanitized.lineSequence().forEach { line ->
        val key0 = line.substringBefore('=', "").trim().lowercase()
        if (key0 in setOf("privatekey", "presharedkey", "publickey")) {
            println("${line.substringBefore('=').trim()} = <скрыт, ${line.substringAfter('=').trim().length} симв.>")
        } else {
            println(line)
        }
    }

    val engineKeys = setOf(
        "privatekey", "listenport", "address", "dns", "mtu", "table",
        "jc", "jmin", "jmax", "s1", "s2", "s3", "s4",
        "h1", "h2", "h3", "h4", "i1", "i2", "i3", "i4", "i5",
        "publickey", "presharedkey", "allowedips", "endpoint", "persistentkeepalive",
    )
    val strangers = sanitized.lineSequence()
        .map { it.substringBefore('=', "").trim().lowercase() }
        .filter { it.isNotEmpty() && it !in engineKeys }
        .toList()
    println("--- ключи, которых движок не знает: ${strangers.ifEmpty { listOf("нет") }} ---")
}
