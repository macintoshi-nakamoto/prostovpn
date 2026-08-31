package com.prostovpn.app

import android.content.Context
import android.content.Intent
import android.net.VpnService
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Живая проверка запасного протокола: поднимает Reality на настоящем узле и
 * смотрит, что трафик действительно уходит через него.
 *
 * Только на устройстве и только руками. Поднять VpnService из обычного теста
 * нельзя — права на это есть лишь у самого процесса приложения; а ещё тест
 * заворачивает весь трафик машины, поэтому в общий прогон ему нельзя.
 *
 * Параметры доступа берутся из аргументов запуска, чтобы не хранить чужие
 * ключи в репозитории:
 *
 *   gradlew connectedDebugAndroidTest \
 *     -Pandroid.testInstrumentationRunnerArguments.vlessHost=... \
 *     -Pandroid.testInstrumentationRunnerArguments.vlessId=... \
 *     ... и так далее
 */
@RunWith(AndroidJUnit4::class)
class VlessLiveTest {

    private val context: Context
        get() = InstrumentationRegistry.getInstrumentation().targetContext

    private val args get() = InstrumentationRegistry.getArguments()

    private fun access(): XrayTunnel.Access? {
        val host = args.getString("vlessHost").orEmpty()
        val id = args.getString("vlessId").orEmpty()
        val key = args.getString("vlessKey").orEmpty()
        if (host.isEmpty() || id.isEmpty() || key.isEmpty()) return null
        return XrayTunnel.Access(
            host = host,
            port = args.getString("vlessPort")?.toIntOrNull() ?: 443,
            id = id,
            publicKey = key,
            shortId = args.getString("vlessShortId").orEmpty(),
            serverName = args.getString("vlessSni") ?: "www.google.com",
            fingerprint = "chrome",
            flow = args.getString("vlessFlow").orEmpty(),
        )
    }

    @After
    fun tearDown() {
        VlessVpnService.stop(context)
        Thread.sleep(1500)
    }

    @Test
    fun tunnelRisesAndCarriesTraffic() {
        val access = access()
        assumeTrue("параметры доступа не переданы — проверять нечего", access != null)

        allowVpn()
        VlessVpnService.start(context, access!!)

        val deadline = System.currentTimeMillis() + 30_000
        while (System.currentTimeMillis() < deadline &&
            VlessVpnService.state == VlessVpnService.State.IDLE
        ) {
            Thread.sleep(300)
        }

        assertEquals(
            "служба не подняла туннель: ${VlessVpnService.failure}",
            VlessVpnService.State.RUNNING,
            VlessVpnService.state,
        )

        // Своим трафиком проверять нельзя: приложение намеренно исключено из
        // туннеля, иначе трафик ядра до узла ушёл бы в туннель, который это
        // же ядро и держит. Поэтому держим туннель поднятым, а выходной адрес
        // смотрит снаружи — из adb shell, чей трафик как раз идёт через нас.
        val hold = args.getString("holdSeconds")?.toLongOrNull() ?: 0L
        if (hold > 0) Thread.sleep(hold * 1000)
    }


    /**
     * Соглашается на туннель за человека.
     *
     * Первый VpnService в системе всегда спрашивает разрешение отдельным
     * окном, и без нажатия establish() молча вернёт null — ровно так эта
     * проверка и падала поначалу.
     */
    private fun allowVpn() {
        val intent: Intent = VpnService.prepare(context) ?: return
        context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))

        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        val button = device.wait(Until.findObject(By.textStartsWith("OK")), 8_000)
            ?: device.wait(Until.findObject(By.textStartsWith("ОК")), 2_000)
            ?: device.wait(Until.findObject(By.textContains("Allow")), 2_000)
        button?.click()
        Thread.sleep(1500)
    }

}
