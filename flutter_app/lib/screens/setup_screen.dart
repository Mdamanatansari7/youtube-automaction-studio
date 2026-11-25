import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../engine.dart';
import '../theme.dart';
import 'home_screen.dart';

/// First run on "This phone": everything the engine needs, checked live, each with its own button.
/// Required: Termux and the engine inside it. Recommended: notifications and the two battery settings (24 h lives).
/// Comes back here any time from the menu → Phone setup.
class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key});

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> with WidgetsBindingObserver {
  Map<String, dynamic> termux = {};
  Map<String, dynamic> battery = {};
  bool notifications = true;
  bool permission = false;
  String want = '';
  String installed = ''; // engine version known to be in Termux
  bool running = false;
  bool busy = false;
  bool autoStart = true;
  String stage = '';
  String? problem;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    load();
    timer = Timer.periodic(const Duration(seconds: 3), (_) => refresh());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    timer?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) refresh(); // back from Termux, the Play Store or a settings page
  }

  Future<void> load() async {
    want = await Engine.bundledVersion();
    installed = await Engine.knownVersion();
    autoStart = await Engine.autoStart();
    await refresh();
  }

  Future<void> refresh() async {
    final t = await Engine.termuxInfo();
    final b = await Engine.battery();
    final n = await Engine.notificationsAllowed();
    final p = await Engine.hasPermission();
    final v = await Api.instance.engineVersion();
    final known = await Engine.knownVersion();
    if (!mounted) return;
    setState(() {
      termux = t;
      battery = b;
      notifications = n;
      permission = p;
      running = v != null;
      installed = (v != null && v.isNotEmpty) ? v : known;
    });
  }

  bool get hasTermux => termux['installed'] == true;
  bool get engineReady => installed.isNotEmpty && installed == want;

  Future<void> installEngine() async {
    setState(() {
      busy = true;
      problem = null;
      stage = 'Starting…';
    });
    final p = await startEngineGuided(context, (s) {
      if (mounted) setState(() => stage = s);
    });
    if (!mounted) return;
    setState(() {
      busy = false;
      problem = p;
      stage = p == null ? 'Engine installed and running ✓' : '';
    });
    await refresh();
  }

  Future<void> finish() async {
    await Engine.setSetupDone(true);
    await Engine.setAutoStart(autoStart);
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const HomeScreen()));
  }

  Widget step({
    required int n,
    required String title,
    required String text,
    required bool ok,
    bool required = false,
    String? button,
    VoidCallback? onPressed,
    Widget? extra,
  }) {
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          CircleAvatar(
            radius: 15,
            backgroundColor: ok ? Neon.green : const Color(0xFF3A2C4D),
            child: ok
                ? const Icon(Icons.check, size: 18, color: Colors.black)
                : Text('$n', style: const TextStyle(fontWeight: FontWeight.w900, color: Neon.white)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(child: Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800))),
                const SizedBox(width: 6),
                Text(required ? 'REQUIRED' : 'RECOMMENDED',
                    style: TextStyle(fontSize: 9.5, letterSpacing: 1, fontWeight: FontWeight.w800, color: required ? Neon.pink : Neon.muted)),
              ]),
              const SizedBox(height: 4),
              Text(text, style: const TextStyle(color: Neon.muted, height: 1.4)),
              ?extra,
              if (!ok && button != null) ...[
                const SizedBox(height: 10),
                FilledButton(
                  onPressed: onPressed,
                  style: FilledButton.styleFrom(backgroundColor: required ? Neon.pink : Neon.green, foregroundColor: Colors.black),
                  child: Text(button),
                ),
              ],
            ]),
          ),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final play = termux['play'] == true;
    final runCommand = termux['runCommand'] == true;
    var n = 0;
    return Scaffold(
      appBar: AppBar(title: const Text('Set up this phone')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text('Everything the engine needs, once. Each step checks itself; come back here any time from the menu.',
                style: TextStyle(color: Neon.muted, height: 1.4)),
            const SizedBox(height: 14),
            step(
              n: ++n,
              title: 'Termux app',
              required: true,
              ok: hasTermux,
              text: !hasTermux
                  ? 'The engine runs inside Termux (free). Install it, open it once, then come back here.'
                  : play
                      ? 'Installed (Play Store version ${termux['version']}). Ninja Studio talks to it through a small helper; '
                          'after a phone restart Termux opens for a second when the engine starts.'
                      : 'Installed (${termux['version']}). Ninja Studio can start the engine in the background.',
              button: 'Install Termux',
              onPressed: Engine.installTermux,
            ),
            if (runCommand)
              step(
                n: ++n,
                title: 'Let Ninja Studio use Termux',
                ok: permission,
                text: 'Android asks: “Run commands in Termux environment”. Allow it, so the engine starts without opening Termux.',
                button: 'Allow',
                onPressed: () async {
                  await Engine.askPermission();
                  refresh();
                },
              ),
            step(
              n: ++n,
              title: 'Install the engine in Termux',
              required: true,
              ok: engineReady,
              text: engineReady
                  ? 'Installed${running ? ' and running' : ''} (version $installed).'
                  : installed.isNotEmpty
                      ? 'An older engine is installed. Update it (a minute or two).'
                      : 'Python, FFmpeg and the engine, about 400 MB. The first time you paste one line in Termux '
                          '(we copy it for you); it takes 5–10 minutes and comes back here.',
              button: busy ? 'Working…' : (installed.isNotEmpty ? 'Update engine' : 'Install engine'),
              onPressed: busy || !hasTermux ? null : installEngine,
              extra: (busy || stage.isNotEmpty || problem != null)
                  ? Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Row(children: [
                        if (busy) const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
                        if (busy) const SizedBox(width: 8),
                        Expanded(
                          child: Text(problem ?? stage,
                              style: TextStyle(color: problem != null ? const Color(0xFFFF7A90) : Neon.green, fontWeight: FontWeight.w700)),
                        ),
                      ]),
                    )
                  : null,
            ),
            step(
              n: ++n,
              title: 'Notifications',
              ok: notifications,
              text: 'Shows when the engine is being prepared, so Android does not stop it halfway.',
              button: 'Allow notifications',
              onPressed: () async {
                await Engine.askNotifications();
                refresh();
              },
            ),
            step(
              n: ++n,
              title: 'Keep Ninja Studio running',
              ok: battery['app'] == true,
              text: 'Lets Android leave this app awake in the background (Battery → Unrestricted).',
              button: 'Allow',
              onPressed: Engine.askAppBattery,
            ),
            step(
              n: ++n,
              title: 'Keep Termux running (24 h lives)',
              ok: battery['termux'] == true,
              text: 'In the page that opens: Battery (App battery usage) → Unrestricted. Then come back.',
              button: 'Open Termux settings',
              onPressed: Engine.termuxBattery,
            ),
            const SizedBox(height: 4),
            SwitchListTile(
              value: autoStart,
              onChanged: (v) => setState(() => autoStart = v),
              title: const Text('Start the engine when the app opens'),
              subtitle: const Text('No button to press: the engine is ready whenever you open Ninja Studio.'),
              activeThumbColor: Neon.green,
            ),
            const SizedBox(height: 10),
            FilledButton.icon(
              key: const Key('setup-done'),
              onPressed: hasTermux && engineReady ? finish : null,
              style: FilledButton.styleFrom(backgroundColor: Neon.pink, foregroundColor: Colors.black, minimumSize: const Size.fromHeight(52)),
              icon: const Icon(Icons.rocket_launch),
              label: Text(hasTermux && engineReady ? 'All set, open Ninja Studio' : 'Finish the required steps first'),
            ),
            TextButton(onPressed: finish, child: const Text('Skip for now')),
          ],
        ),
      ),
    );
  }
}
