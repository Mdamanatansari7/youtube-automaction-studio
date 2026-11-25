// "This phone" mode: the Ninja Studio engine (the same Python app as on the PC) runs inside Termux on this phone.
// The engine code is bundled in this app (assets/engine, made by tool/pack_engine.sh).
// Two ways to reach Termux (see MainActivity.kt):
//   * Termux from GitHub / F-Droid takes commands from this app directly (RUN_COMMAND).
//   * Termux from the Play Store does not: the agent the setup puts in Termux (~/ninjastudio-agent.sh) asks this app's
//     helper (EngineService, 127.0.0.1:8898) what to do every few seconds. When it is not running yet (phone restarted),
//     this app opens Termux for a moment; the new Termux session starts the agent, which starts the engine and comes back.
// The very first time, one line has to be pasted in Termux (only Termux itself can install the agent); after that
// Start engine, updates and stop work by themselves. The setup screen (screens/setup_screen.dart) walks through it.
import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'theme.dart';

class Engine {
  static const _ch = MethodChannel('ninja/engine');
  static const pasteCommand = 'curl -s 127.0.0.1:8898/setup | bash';

  static Future<T?> _call<T>(String m, [Map<String, Object?>? a]) async {
    if (!Platform.isAndroid) return null;
    try {
      return await _ch.invokeMethod<T>(m, a);
    } on MissingPluginException {
      return null;
    }
  }

  static Future<bool> termuxInstalled() async => await _call<bool>('termuxInstalled') ?? false;
  static Future<Map<String, dynamic>> termuxInfo() async => Map<String, dynamic>.from(await _call<Map>('termuxInfo') ?? {});
  static Future<bool> hasPermission() async => await _call<bool>('hasPermission') ?? false;
  static Future<void> askPermission() => _call('askPermission');
  static Future<String?> run(String script) => _call<String>('run', {'script': script});
  static Future<String?> bash(String command, {bool visible = false}) => _call<String>('bash', {'command': command, 'visible': visible});
  static Future<void> openTermux() => _call('openTermux');
  static Future<void> installTermux() => _call('installTermux');
  static Future<void> termuxBattery() => _call('termuxBattery');
  static Future<void> askAppBattery() => _call('askAppBattery');
  static Future<Map<String, dynamic>> battery() async => Map<String, dynamic>.from(await _call<Map>('battery') ?? {});
  static Future<bool> notificationsAllowed() async => await _call<bool>('notificationsAllowed') ?? true;
  static Future<void> askNotifications() => _call('askNotifications');
  static Future<void> openUrl(String url) => _call('openUrl', {'url': url});
  static Future<String?> startHelper() => _call<String>('setupServer');
  static Future<void> stopHelper() => _call('setupStop');
  static Future<void> setCommand(String command, {bool back = false}) => _call('setCommand', {'command': command, 'back': back});
  static Future<Map<String, dynamic>> helperState() async => Map<String, dynamic>.from(await _call<Map>('setupState') ?? {});
  static Future<String> bundledVersion() async => (await rootBundle.loadString('assets/engine/ENGINE_VERSION')).trim();

  // ---- remembered on the phone: setup finished, start with the app, the engine version Termux last reported
  static Future<SharedPreferences> get _p => SharedPreferences.getInstance();
  static Future<bool> setupDone() async => (await _p).getBool('setup_done') ?? false;
  static Future<void> setSetupDone(bool v) async => (await _p).setBool('setup_done', v);
  static Future<bool> autoStart() async => (await _p).getBool('auto_start') ?? true;
  static Future<void> setAutoStart(bool v) async => (await _p).setBool('auto_start', v);
  static Future<String> knownVersion() async => (await _p).getString('engine_version') ?? '';
  static Future<void> _remember(String v) async {
    if (v.isNotEmpty) await (await _p).setString('engine_version', v);
  }

  /// Waits until the agent in Termux has taken the pending command. False when no agent asked in time.
  static Future<bool> _agentTook({required int seconds}) async {
    for (var i = 0; i < seconds * 4; i++) {
      final s = await helperState();
      if ((s['pending'] ?? '') == '' && (s['agentAgo'] ?? -1) >= 0) {
        await _remember('${s['version'] ?? ''}');
        return true;
      }
      await Future.delayed(const Duration(milliseconds: 250));
    }
    return false;
  }

  /// Starts (and if needed sets up or updates) the engine. Returns null when it runs, 'termux' / 'paste' for the two
  /// guided cases, or an error text. [stage] gets short progress texts.
  static Future<String?> start(void Function(String) stage) async {
    final t = await termuxInfo();
    if (t['installed'] != true) return 'termux';
    final want = await bundledVersion();
    final running = await Api.instance.engineVersion();
    if (running != null && running == want) {
      await _remember(running);
      return null;
    }
    final helper = await startHelper();
    if (helper != null) return 'Could not start the setup helper: $helper';
    await Future.delayed(const Duration(milliseconds: 400));

    // Termux from GitHub / F-Droid with the permission given (the setup screen asks for it): ask it directly,
    // which works even when Termux is closed. Never asked here, so a "Don't allow" does not come back at every start.
    if (t['runCommand'] == true) {
      if (await hasPermission()) {
        stage('Asking Termux…');
        final refused = await bash(r'curl -s -m 3 "http://127.0.0.1:8898/ping?v=$(cat $HOME/ninjastudio/ENGINE_VERSION 2>/dev/null)"');
        var s = <String, dynamic>{};
        for (var i = 0; refused == null && i < 32; i++) {
          s = await helperState();
          if (s['pinged'] == true) break;
          await Future.delayed(const Duration(milliseconds: 250));
        }
        if (s['pinged'] == true) {
          await _remember('${s['version'] ?? ''}');
          if (s['version'] == want) {
            stage('Starting the engine…');
            await bash(r'$HOME/ninjastudio-stop.sh >/dev/null 2>&1; $HOME/ninjastudio-start.sh');
          } else {
            stage((s['version'] ?? '').toString().isEmpty ? 'Setting up the engine in Termux (first time: 5–10 min)…' : 'Updating the engine in Termux…');
            await bash(pasteCommand, visible: true);
            // Android does not let Termux bring itself to the front from the background, so this app opens it.
            await Future.delayed(const Duration(milliseconds: 800));
            await openTermux();
          }
          return waitUntilRunning(stage);
        }
        // Termux refused (allow-external-apps still off): the agent may still be there, try it below.
      }
    }

    // Any Termux (also the Play Store one): the agent inside Termux.
    stage('Asking the helper in Termux…');
    await setCommand('go');
    if (await _agentTook(seconds: 5)) return waitUntilRunning(stage);
    if ((await knownVersion()).isEmpty) {
      await setCommand('');
      return 'paste'; // never installed from this app: the one-time paste (opening Termux would not help yet)
    }
    // No agent running (phone restarted, or Termux closed): open Termux; its new session starts the agent, which comes back.
    stage('Opening Termux for a moment…');
    await setCommand('go', back: true);
    await openTermux();
    if (await _agentTook(seconds: 20)) return waitUntilRunning(stage);
    await setCommand('');
    return 'paste'; // the agent is not installed yet: the one-time paste
  }

  /// True when the running engine is older than the one bundled in this app.
  static Future<bool> outdated() async {
    final v = await Api.instance.engineVersion();
    return v != null && v != await bundledVersion();
  }

  /// True while the engine is working (a live, Go Live, Make clips…): no update then.
  static Future<bool> busy() async {
    try {
      final live = await Api.instance.getJson('/golive-active');
      final jobs = await Api.instance.getJson('/runtime');
      return (live is Map && live['live'] != null) || (jobs is Map && (jobs['active'] as List? ?? []).isNotEmpty);
    } catch (_) {
      return true; // not sure: leave it alone
    }
  }

  /// Stops the engine (through Termux directly, or through the agent).
  static Future<String?> stop() async {
    if (await hasPermission()) return run('ninjastudio-stop.sh');
    final helper = await startHelper();
    if (helper != null) return helper;
    await setCommand('stop');
    if (await _agentTook(seconds: 6)) return null;
    await setCommand('');
    return 'Termux is not running, so the engine is already off.';
  }

  /// Waits for the current engine to answer (a first setup can take a while), showing the setup progress.
  static Future<String?> waitUntilRunning(void Function(String) stage, {int minutes = 20}) async {
    final want = await bundledVersion();
    final end = DateTime.now().add(Duration(minutes: minutes));
    while (DateTime.now().isBefore(end)) {
      final v = await Api.instance.engineVersion();
      if (v != null && (v == want || v.isEmpty && (await helperState())['done'] == true)) {
        await _remember(v);
        await stopHelper();
        return null;
      }
      final s = await helperState();
      if ((s['failed'] ?? '').toString().isNotEmpty) return '${s['failed']}'.replaceFirst('failed: ', 'Setup failed: ');
      if ((s['progress'] ?? '').toString().isNotEmpty) {
        stage('Termux: ${s['progress']}');
      } else {
        stage('Starting the engine…');
      }
      await Future.delayed(const Duration(seconds: 2));
    }
    return 'The engine did not start. Open Termux to see what happened.';
  }
}

/// Runs [Engine.start] and handles the two guided cases. Returns an error text or null.
Future<String?> startEngineGuided(BuildContext context, void Function(String) stage) async {
  var problem = await Engine.start(stage);
  if (!context.mounted) return problem;
  if (problem == 'termux') {
    showSetupHelp(context, needTermux: true);
    return 'Install Termux first.';
  }
  if (problem == 'paste') {
    await showPasteOnce(context);
    stage('Waiting for Termux… (paste the line there and press Enter)');
    problem = await Engine.waitUntilRunning(stage);
  }
  return problem;
}

/// A thin bar at the top of the app in "This phone" mode: engine running, or off with a Start button.
/// When the setup is done and "Start with the app" is on, it starts the engine by itself when the app opens.
class EngineBar extends StatefulWidget {
  const EngineBar({super.key, this.onSetup});
  final VoidCallback? onSetup;

  @override
  State<EngineBar> createState() => _EngineBarState();
}

class _EngineBarState extends State<EngineBar> {
  bool? up;
  bool starting = false;
  bool ready = true; // setup done
  String stage = '';
  Timer? timer;

  @override
  void initState() {
    super.initState();
    first();
    timer = Timer.periodic(const Duration(seconds: 5), (_) => check());
  }

  Future<void> first() async {
    ready = await Engine.setupDone();
    await check();
    if (!Api.instance.local || !ready || !await Engine.autoStart() || !mounted || starting) return;
    if (up == false) {
      start();
    } else if (up == true && await Engine.outdated() && !await Engine.busy() && mounted) {
      start(); // this app brought a newer engine: update it now, while nothing is running (never in the middle of a live)
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> check() async {
    final ok = await Api.instance.healthy();
    if (mounted && ok != up) setState(() => up = ok);
  }

  void setStage(String s) {
    if (mounted) setState(() => stage = s);
  }

  Future<void> start() async {
    setState(() {
      starting = true;
      stage = 'Starting…';
    });
    final problem = await startEngineGuided(context, setStage);
    if (problem != null && mounted) toast(context, problem, bad: true);
    if (mounted) setState(() => starting = false);
    check();
  }

  @override
  Widget build(BuildContext context) {
    if (!Api.instance.local) return const SizedBox.shrink();
    final running = up == true;
    return Material(
      color: running ? const Color(0xFF0F2A17) : const Color(0xFF3A0F18),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 6, 8, 6),
        child: Row(children: [
          Icon(running ? Icons.check_circle : Icons.power_settings_new, size: 18, color: running ? Neon.green : Colors.redAccent),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              running ? 'Engine running on this phone' : starting ? stage : up == null ? 'Checking the engine…' : 'Engine is off',
              style: const TextStyle(fontWeight: FontWeight.w700),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (!running && up != null && !ready && widget.onSetup != null)
            TextButton(onPressed: widget.onSetup, child: const Text('Setup')),
          if (!running && up != null)
            FilledButton(
              key: const Key('engine-start'),
              onPressed: starting ? null : start,
              style: FilledButton.styleFrom(backgroundColor: Neon.pink, foregroundColor: Colors.black, visualDensity: VisualDensity.compact),
              child: Text(starting ? 'Starting…' : 'Start engine'),
            ),
        ]),
      ),
    );
  }
}

/// The one-time step: only Termux itself can install the engine and its agent. The line below does it; after it,
/// Start engine works by itself.
Future<void> showPasteOnce(BuildContext context) async {
  await Clipboard.setData(const ClipboardData(text: Engine.pasteCommand));
  if (!context.mounted) return;
  await showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (c) => AlertDialog(
      title: const Text('One time only'),
      content: const Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('The engine has to be installed inside Termux once. We copied the line for you.'),
        SizedBox(height: 12),
        Text('1. Press “Open Termux”\n2. Long-press in Termux → Paste\n3. Press Enter\n\nIt installs everything (5–10 min) and comes back here. '
            'After this, Start engine works by itself, also after a phone restart.', style: TextStyle(height: 1.45)),
        SizedBox(height: 12),
        SelectableText(Engine.pasteCommand, style: TextStyle(fontFamily: 'monospace', fontSize: 13, color: Neon.green)),
      ]),
      actions: [
        FilledButton(
          onPressed: () {
            Navigator.pop(c);
            Engine.openTermux();
          },
          child: const Text('Open Termux'),
        ),
      ],
    ),
  );
}

void showSetupHelp(BuildContext context, {bool needTermux = false}) {
  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Neon.panel,
    builder: (c) => SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('Set up this phone', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900)),
          const SizedBox(height: 8),
          if (needTermux) const Text('Termux is not installed yet.', style: TextStyle(color: Colors.redAccent, fontWeight: FontWeight.w700)),
          const Text('1. Install Termux (Play Store, F-Droid or github.com/termux/termux-app/releases) and open it once.\n'
              '2. Come back here and press “Start engine”.\n'
              '3. The first time, paste one line in Termux (the app copies it for you). Everything else is automatic.\n'
              '4. For 24 h lives: Termux → Battery → Unrestricted, and keep the phone on the charger.',
              style: TextStyle(color: Neon.muted, height: 1.5)),
          const SizedBox(height: 12),
          Wrap(spacing: 10, children: [
            if (needTermux) FilledButton(onPressed: Engine.installTermux, child: const Text('Install Termux')),
            OutlinedButton(onPressed: Engine.openTermux, child: const Text('Open Termux')),
            OutlinedButton(onPressed: Engine.termuxBattery, child: const Text('Termux battery setting')),
          ]),
        ]),
      ),
    ),
  );
}
