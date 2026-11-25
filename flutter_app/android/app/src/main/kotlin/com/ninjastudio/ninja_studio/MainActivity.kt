package com.ninjastudio.ninja_studio

import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/**
 * "This phone" mode: the Ninja Studio engine (the same Python app as on the PC) runs inside Termux on the phone.
 * Two ways to reach it:
 *   * Termux from GitHub / F-Droid: its RUN_COMMAND service runs commands for this app directly (needs the
 *     "Run commands in Termux environment" permission and allow-external-apps, set by the setup).
 *   * Termux from the Play Store has no RUN_COMMAND: the agent the setup installs in Termux (~/ninjastudio-agent.sh)
 *     asks EngineService what to do instead; this app opens Termux when the agent is not running yet.
 * The channel also reports what the setup screen checks (Termux build, battery, notifications).
 */
class MainActivity : FlutterActivity() {
    private val termux = "com.termux"
    private val permission = "com.termux.permission.RUN_COMMAND"
    private val home = "/data/data/com.termux/files/home"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "ninja/engine").setMethodCallHandler { call, result ->
            when (call.method) {
                "termuxInstalled" -> result.success(installed(termux))
                "termuxInfo" -> result.success(termuxInfo())
                "hasPermission" -> result.success(runCommandDefined() && checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED)
                "askPermission" -> {
                    if (runCommandDefined()) requestPermissions(arrayOf(permission), 7)
                    result.success(null)
                }
                "run" -> result.success(runInTermux(call.argument<String>("script") ?: "ninjastudio-start.sh"))
                "bash" -> result.success(bashInTermux(call.argument<String>("command") ?: "true", call.argument<Boolean>("visible") ?: false))
                "setupServer" -> {
                    EngineService.reset()
                    val i = Intent(this, EngineService::class.java)
                    result.success(try { if (Build.VERSION.SDK_INT >= 26) startForegroundService(i) else startService(i); null } catch (e: Exception) { e.message ?: e.toString() })
                }
                "setupState" -> result.success(mapOf(
                    "running" to EngineService.running, "pinged" to EngineService.pinged, "version" to EngineService.installedVersion,
                    "progress" to EngineService.progress, "done" to EngineService.done, "failed" to EngineService.failed,
                    "agentAgo" to (if (EngineService.agentSeen == 0L) -1L else System.currentTimeMillis() - EngineService.agentSeen),
                    "pending" to EngineService.command))
                "setCommand" -> {
                    EngineService.command = call.argument<String>("command") ?: ""
                    EngineService.back = call.argument<Boolean>("back") ?: false
                    result.success(null)
                }
                "setupStop" -> { stopService(Intent(this, EngineService::class.java)); result.success(null) }
                "askNotifications" -> {
                    if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 8)
                    result.success(null)
                }
                "notificationsAllowed" -> result.success(getSystemService(NotificationManager::class.java).areNotificationsEnabled())
                "battery" -> {
                    val pm = getSystemService(PowerManager::class.java)
                    result.success(mapOf("app" to pm.isIgnoringBatteryOptimizations(packageName), "termux" to pm.isIgnoringBatteryOptimizations(termux)))
                }
                "askAppBattery" -> result.success(open(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))))
                "installTermux" -> result.success(
                    open(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$termux")))
                        ?.let { open(Intent(Intent.ACTION_VIEW, Uri.parse("https://play.google.com/store/apps/details?id=$termux"))) })
                "openTermux" -> result.success(open(packageManager.getLaunchIntentForPackage(termux)))
                "termuxBattery" -> result.success(open(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$termux"))))
                "openUrl" -> result.success(open(Intent(Intent.ACTION_VIEW, Uri.parse(call.argument<String>("url")))))
                else -> result.notImplemented()
            }
        }
    }

    private fun installed(pkg: String): Boolean = try {
        packageManager.getPackageInfo(pkg, 0)
        true
    } catch (e: PackageManager.NameNotFoundException) {
        false
    }

    /** Termux from the Play Store does not define the RUN_COMMAND permission (and has no RunCommandService). */
    private fun runCommandDefined(): Boolean = try {
        packageManager.getPermissionInfo(permission, 0)
        true
    } catch (e: PackageManager.NameNotFoundException) {
        false
    }

    private fun termuxInfo(): Map<String, Any?> {
        val info = try { packageManager.getPackageInfo(termux, 0) } catch (e: PackageManager.NameNotFoundException) { null }
        val installer = try {
            if (Build.VERSION.SDK_INT >= 30) packageManager.getInstallSourceInfo(termux).installingPackageName
            else @Suppress("DEPRECATION") packageManager.getInstallerPackageName(termux)
        } catch (e: Exception) { null }
        return mapOf(
            "installed" to (info != null),
            "version" to (info?.versionName ?: ""),
            "play" to (installer == "com.android.vending" || (info?.versionName ?: "").startsWith("googleplay")),
            "runCommand" to runCommandDefined(),
        )
    }

    /** Returns null when Termux accepted the command, otherwise the reason. */
    private fun runInTermux(script: String): String? {
        if (!runCommandDefined()) return "This Termux takes no commands from apps"
        val intent = Intent().apply {
            setClassName(termux, "com.termux.app.RunCommandService")
            action = "com.termux.RUN_COMMAND"
            putExtra("com.termux.RUN_COMMAND_PATH", "$home/$script")
            putExtra("com.termux.RUN_COMMAND_WORKDIR", home)
            putExtra("com.termux.RUN_COMMAND_BACKGROUND", true)
        }
        return try {
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent) else startService(intent)
            null
        } catch (e: Exception) {
            e.message ?: e.toString()
        }
    }

    /** Runs a bash command in Termux. visible = Termux opens and shows it (used for the setup), else it runs in the background. */
    private fun bashInTermux(command: String, visible: Boolean): String? {
        if (!runCommandDefined()) return "This Termux takes no commands from apps"
        val intent = Intent().apply {
            setClassName(termux, "com.termux.app.RunCommandService")
            action = "com.termux.RUN_COMMAND"
            putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/bash")
            putExtra("com.termux.RUN_COMMAND_ARGUMENTS", arrayOf("-c", command))
            putExtra("com.termux.RUN_COMMAND_WORKDIR", home)
            putExtra("com.termux.RUN_COMMAND_BACKGROUND", !visible)
            if (visible) putExtra("com.termux.RUN_COMMAND_SESSION_ACTION", "0")    // new session, bring Termux to the front
        }
        return try {
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent) else startService(intent)
            null
        } catch (e: Exception) {
            e.message ?: e.toString()
        }
    }

    private fun open(intent: Intent?): String? {
        if (intent == null) return "not installed"
        return try {
            startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            null
        } catch (e: Exception) {
            e.message ?: e.toString()
        }
    }
}
