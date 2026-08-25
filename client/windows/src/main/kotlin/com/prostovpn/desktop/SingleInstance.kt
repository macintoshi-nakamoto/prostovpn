package com.prostovpn.desktop

import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.channels.FileChannel
import java.nio.channels.FileLock
import java.nio.file.StandardOpenOption

object SingleInstance {
    private val dir = File(System.getenv("LOCALAPPDATA") ?: System.getProperty("user.home"), "ProstoVPN")

    private val lockFile = File(dir, "instance.lock")
    private val portFile = File(dir, "instance.port")

    private var channel: FileChannel? = null
    private var lock: FileLock? = null
    private var server: ServerSocket? = null

    fun acquire(onShowRequest: () -> Unit): Boolean {
        dir.mkdirs()

        val ch = runCatching {
            FileChannel.open(
                lockFile.toPath(),
                StandardOpenOption.CREATE,
                StandardOpenOption.WRITE,
            )
        }.getOrNull() ?: return true

        val fl = runCatching { ch.tryLock() }.getOrNull()
        if (fl == null) {
            runCatching { ch.close() }
            askRunningInstanceToShow()
            return false
        }

        channel = ch
        lock = fl
        startShowListener(onShowRequest)
        return true
    }

    private fun startShowListener(onShowRequest: () -> Unit) {
        runCatching {
            val socket = ServerSocket(0, 1, InetAddress.getLoopbackAddress())
            server = socket
            portFile.writeText(socket.localPort.toString())

            Thread {
                while (!socket.isClosed) {
                    runCatching {
                        socket.accept().use { onShowRequest() }
                    }
                }
            }.apply {
                isDaemon = true
                name = "single-instance"
                start()
            }
        }
    }

    private fun askRunningInstanceToShow() {
        runCatching {
            val port = portFile.readText().trim().toInt()
            Socket(InetAddress.getLoopbackAddress(), port).close()
        }
    }
}
