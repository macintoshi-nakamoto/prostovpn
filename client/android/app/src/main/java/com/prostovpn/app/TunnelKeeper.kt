package com.prostovpn.app

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.util.Log

object NetworkInfo {
    private fun manager(context: Context): ConnectivityManager? =
        runCatching { context.getSystemService(ConnectivityManager::class.java) }.getOrNull()

    fun isOnline(context: Context): Boolean {
        val cm = manager(context) ?: return true
        val network = runCatching { cm.activeNetwork }.getOrNull() ?: return false
        val caps = runCatching { cm.getNetworkCapabilities(network) }.getOrNull() ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    fun currentNetworkId(context: Context): String {
        val cm = manager(context) ?: return ""
        return runCatching { cm.activeNetwork?.toString() }.getOrNull().orEmpty()
    }

    fun kind(context: Context): String {
        val cm = manager(context) ?: return "unknown"
        val caps = runCatching { cm.getNetworkCapabilities(cm.activeNetwork) }.getOrNull()
            ?: return "none"
        return when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            else -> "other"
        }
    }

    fun watch(context: Context, onChanged: () -> Unit): (() -> Unit)? {
        val cm = manager(context) ?: return null
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = onChanged()
            override fun onLost(network: Network) = onChanged()
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                onChanged()
            }
        }
        return runCatching {
            cm.registerDefaultNetworkCallback(callback)
            val undo: () -> Unit = { runCatching { cm.unregisterNetworkCallback(callback) } }
            undo
        }.onFailure { Log.w(TAG, "не удалось подписаться на смену сети", it) }.getOrNull()
    }

    private const val TAG = "ProstoNet"
}

object Endpoints {
    private val ENDPOINT = Regex("""(?im)^(\s*Endpoint\s*=\s*)(\S+?)(?::(\d+))?\s*$""")

    fun portOf(config: String): Int =
        ENDPOINT.find(config)?.groupValues?.getOrNull(3)?.toIntOrNull() ?: 0

    fun withPort(config: String, port: Int): String =
        ENDPOINT.replace(config) { m -> "${m.groupValues[1]}${m.groupValues[2]}:$port" }

    fun order(configPort: Int, remembered: Int, alternatives: List<Int>): List<Int> {
        val out = ArrayList<Int>(alternatives.size + 2)
        if (remembered > 0) out.add(remembered)
        if (configPort > 0 && configPort !in out) out.add(configPort)
        for (p in alternatives) if (p > 0 && p !in out) out.add(p)
        return out
    }
}
