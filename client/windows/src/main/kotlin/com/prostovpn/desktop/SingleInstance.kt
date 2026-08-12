package com.prostovpn.desktop

import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.channels.FileChannel
import java.nio.channels.FileLock
import java.nio.file.StandardOpenOption

/**
 * Ровно один экземпляр приложения.
 *
 * Это не удобство, а защита установки. Крестик прячет окно в трей, и
 * человек, не найдя приложения на экране, запускает его с ярлыка ещё раз —
 * теперь их два, и оба держат байт-код в папке установки. Ровно так
 * сломалось обновление: помощник дождался выхода того экземпляра, который
 * его запустил, а второй продолжал держать файлы. MSI упёрся в занятые
 * библиотеки, отложил замену «на перезагрузку», и после неё в папке
 * осталось два jar-файла из тридцати семи — приложение перестало
 * запускаться вовсе.
 *
 * Механика: файловый замок в каталоге данных приложения. Первый экземпляр
 * захватывает его на всё время жизни и слушает локальный порт; второй,
 * увидев занятый замок, просит первого показать окно и выходит. Для
 * человека повторный запуск выглядит как «приложение открылось» — то есть
 * ровно так, как он и ожидал.
 */
object SingleInstance {

    private val dir = File(System.getenv("LOCALAPPDATA") ?: System.getProperty("user.home"), "ProstoVPN")

    private val lockFile = File(dir, "instance.lock")
    private val portFile = File(dir, "instance.port")

    // Держим ссылки живыми: собранный сборщиком мусора FileLock отпускает
    // замок, и защита молча исчезает посреди работы.
    private var channel: FileChannel? = null
    private var lock: FileLock? = null
    private var server: ServerSocket? = null

    /**
     * Пытается стать единственным экземпляром.
     *
     * @param onShowRequest зовётся, когда человек запустил приложение ещё
     *   раз: первый экземпляр должен показать окно. Приходит из фонового
     *   потока — вызывающему поднимать на свой.
     * @return false — уже работает другой экземпляр; ему передана просьба
     *   показаться, а этому процессу надо тихо выйти.
     */
    fun acquire(onShowRequest: () -> Unit): Boolean {
        dir.mkdirs()

        val ch = runCatching {
            FileChannel.open(
                lockFile.toPath(),
                StandardOpenOption.CREATE,
                StandardOpenOption.WRITE,
            )
        }.getOrNull() ?: return true // Не смогли открыть замок — не мешаем запуску.

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

    /**
     * Локальный порт, на котором первый экземпляр ждёт просьбы показаться.
     *
     * Порт случайный и записан в файл рядом с замком. Слушаем только
     * loopback: с других машин сюда не достучаться.
     */
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

    /**
     * Просит работающий экземпляр показать окно.
     *
     * Достаточно самого подключения — ничего передавать не нужно. Если
     * порт устарел или никто не ответил, просто выходим молча: экземпляр
     * есть (замок занят), а показаться он не смог — не повод плодить второй.
     */
    private fun askRunningInstanceToShow() {
        runCatching {
            val port = portFile.readText().trim().toInt()
            Socket(InetAddress.getLoopbackAddress(), port).close()
        }
    }
}
