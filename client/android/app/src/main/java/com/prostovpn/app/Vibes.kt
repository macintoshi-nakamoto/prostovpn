package com.prostovpn.app

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

/**
 * Свои вибрации на подключение и отключение.
 *
 * Системные клики одинаковы у всех — а момент, когда туннель поднялся,
 * стоит того, чтобы его узнавали на ощупь. Подключение: два коротких
 * толчка по нарастающей и мягкий длинный — «поехали». Отключение: один
 * плотный и затухающий хвост — «выдох». Амплитуды работают только на
 * моторах с их поддержкой; остальным достаётся тот же ритм.
 */
object Vibes {
    private val CONNECT_TIMINGS = longArrayOf(0, 16, 70, 22, 70, 50)
    private val CONNECT_LEVELS = intArrayOf(0, 90, 0, 160, 0, 255)

    private val DISCONNECT_TIMINGS = longArrayOf(0, 46, 55, 18)
    private val DISCONNECT_LEVELS = intArrayOf(0, 255, 0, 70)

    fun connected(context: Context) = play(context, CONNECT_TIMINGS, CONNECT_LEVELS)

    fun disconnected(context: Context) = play(context, DISCONNECT_TIMINGS, DISCONNECT_LEVELS)

    private fun vibrator(context: Context): Vibrator? = runCatching {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            (context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager)
                ?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        }
    }.getOrNull()

    private fun play(context: Context, timings: LongArray, levels: IntArray) {
        val motor = vibrator(context) ?: return
        if (!motor.hasVibrator()) return
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val effect = if (motor.hasAmplitudeControl()) {
                    VibrationEffect.createWaveform(timings, levels, -1)
                } else {
                    VibrationEffect.createWaveform(timings, -1)
                }
                motor.vibrate(effect)
            } else {
                @Suppress("DEPRECATION")
                motor.vibrate(timings, -1)
            }
        }
    }
}
