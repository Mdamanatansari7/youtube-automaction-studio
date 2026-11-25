package com.ninjastudio.ninja_studio

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import io.flutter.FlutterInjector
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import kotlin.concurrent.thread

/**
 * Hands the engine (bundled in the app as assets/engine/engine.tgz) to Termux on this phone, so setting up the
 * engine needs no GitHub and no laptop. A tiny HTTP server on 127.0.0.1:8898 (this phone only) serves:
 *   /setup       the bootstrap script Termux runs (curl -s 127.0.0.1:8898/setup | bash)
 *   /engine.tgz  the engine code
 *   /ping?v=..   Termux reports which engine version it has (the app decides: start, or set up / update)
 *   /hello?v=..  the agent in Termux (~/ninjastudio-agent.sh) asks what to do: "none", "start", "setup" or "stop",
 *                plus " back" when the app opened Termux to wake the agent (it then returns to the app)
 *   /progress?m= setup progress shown in the app
 * It runs as a foreground service so Android does not freeze it while Termux is in front, and stops after 30 minutes.
 */
class EngineService : Service() {
    companion object {
        const val PORT = 8898
        @Volatile var running = false
        @Volatile var pinged = false
        @Volatile var installedVersion = ""
        @Volatile var progress = ""
        @Volatile var done = false
        @Volatile var failed = ""
        @Volatile var command = ""          // what the app wants: "go" (start, or set up / update first) or "stop"
        @Volatile var back = false          // the app opened Termux: the agent returns to the app afterwards
        @Volatile var agentSeen = 0L        // when the agent last asked (ms)
        @Volatile var bundledVersion = ""
        fun reset() { pinged = false; installedVersion = ""; progress = ""; done = false; failed = "" }
    }

    private var server: ServerSocket? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundNotice()
        if (!running) {
            running = true
            thread(name = "engine-setup-server", isDaemon = true) { serve() }
            thread(isDaemon = true) { Thread.sleep(30 * 60 * 1000L); stopSelf() }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        running = false
        try { server?.close() } catch (_: Exception) {}
        super.onDestroy()
    }

    private fun startForegroundNotice() {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(NotificationChannel("engine", "Engine setup", NotificationManager.IMPORTANCE_LOW))
        }
        val n: Notification = (if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, "engine") else Notification.Builder(this))
            .setContentTitle("Ninja Studio")
            .setContentText("Preparing the engine in Termux…")
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(7, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC) else startForeground(7, n)
    }

    private fun serve() {
        try {
            val s = ServerSocket(PORT, 16, InetAddress.getByName("127.0.0.1"))
            server = s
            while (running) {
                val c = s.accept()
                thread(isDaemon = true) { handle(c) }
            }
        } catch (_: Exception) {
            running = false
        }
    }

    private fun handle(c: Socket) {
        c.use { sock ->
            sock.soTimeout = 15000
            val reader = BufferedReader(InputStreamReader(sock.getInputStream()))
            val line = reader.readLine() ?: return
            while (true) { val h = reader.readLine() ?: break; if (h.isEmpty()) break }
            val target = line.split(" ").getOrNull(1) ?: "/"
            val path = target.substringBefore("?")
            val query = target.substringAfter("?", "").split("&").filter { it.contains("=") }
                .associate { it.substringBefore("=") to URLDecoder.decode(it.substringAfter("="), "UTF-8") }
            val out = sock.getOutputStream()
            when (path) {
                "/setup" -> send(out, "text/plain", bootstrap().toByteArray())
                "/engine.tgz" -> {
                    val key = FlutterInjector.instance().flutterLoader().getLookupKeyForAsset("assets/engine/engine.tgz")
                    send(out, "application/gzip", assets.open(key).use { it.readBytes() })
                }
                "/ping" -> { installedVersion = query["v"] ?: ""; pinged = true; send(out, "text/plain", "ok".toByteArray()) }
                "/hello" -> {
                    installedVersion = query["v"] ?: ""; pinged = true; agentSeen = System.currentTimeMillis()
                    val cmd = command
                    command = ""
                    val reply = when (cmd) {
                        "stop" -> "stop"
                        "go" -> (if (installedVersion.isNotEmpty() && installedVersion == bundled()) "start" else "setup") + (if (back) " back" else "")
                        else -> "none"
                    }
                    if (cmd.isNotEmpty()) back = false
                    send(out, "text/plain", reply.toByteArray())
                }
                "/progress" -> {
                    val m = query["m"] ?: ""
                    if (m == "done") done = true else if (m.startsWith("failed")) failed = m else progress = m
                    send(out, "text/plain", "ok".toByteArray())
                }
                else -> send(out, "text/plain", "not found".toByteArray(), 404)
            }
        }
    }

    /** The engine version bundled in this app (assets/engine/ENGINE_VERSION). */
    private fun bundled(): String {
        if (bundledVersion.isEmpty()) {
            val key = FlutterInjector.instance().flutterLoader().getLookupKeyForAsset("assets/engine/ENGINE_VERSION")
            bundledVersion = try { assets.open(key).use { it.readBytes() }.toString(Charsets.UTF_8).trim() } catch (_: Exception) { "" }
        }
        return bundledVersion
    }

    private fun send(out: OutputStream, type: String, body: ByteArray, code: Int = 200) {
        out.write("HTTP/1.0 $code OK\r\nContent-Type: $type\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray())
        out.write(body)
        out.flush()
    }

    /** What Termux runs: get the engine from this app, install it with android/termux-setup.sh, (re)start it, go back to the app. */
    private fun bootstrap(): String = """
        |#!/data/data/com.termux/files/usr/bin/bash
        |S=http://127.0.0.1:$PORT
        |p() { curl -s -m 2 -G --data-urlencode "m=${'$'}1" "${'$'}S/progress" >/dev/null 2>&1; }
        |echo
        |echo "  Ninja Studio: setting up the engine on this phone."
        |echo "  The first time takes 5-10 minutes. Keep Termux open; you can watch the progress here."
        |echo
        |p "Getting the engine from the app"
        |mkdir -p "${'$'}HOME/ninjastudio-src" && cd "${'$'}HOME/ninjastudio-src" || exit 1
        |if ! curl -fsS -m 60 "${'$'}S/engine.tgz" -o engine.tgz || ! tar -xzf engine.tgz; then
        |  echo "Could not get the engine from the Ninja Studio app. Open the app and press Start engine again."
        |  p "failed: could not get the engine from the app"; exit 1
        |fi
        |rm -f engine.tgz
        |NINJA_PROGRESS="${'$'}S/progress" bash "${'$'}HOME/ninjastudio-src/android/termux-setup.sh" 2>&1 | tee "${'$'}HOME/ninjastudio-setup.log"
        |if [ "${'$'}{PIPESTATUS[0]}" != "0" ]; then
        |  echo; echo "Setup stopped with an error (details in ~/ninjastudio-setup.log)."
        |  p "failed: setup stopped, see ~/ninjastudio-setup.log in Termux"; exit 1
        |fi
        |"${'$'}HOME/ninjastudio-stop.sh" >/dev/null 2>&1    # an update: the old engine must not keep running
        |"${'$'}HOME/ninjastudio-start.sh"
        |p "done"
        |echo; echo "  Engine started. Going back to the Ninja Studio app…"
        |sleep 2
        |am start -n com.ninjastudio.ninja_studio/.MainActivity >/dev/null 2>&1 || termux-open-url "ninjastudio://open" >/dev/null 2>&1 || true
        |""".trimMargin()
}
