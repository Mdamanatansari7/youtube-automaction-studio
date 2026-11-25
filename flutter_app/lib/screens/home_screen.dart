import 'package:flutter/material.dart';

import '../api.dart';
import '../engine.dart';
import '../theme.dart';
import 'clips_screen.dart';
import 'connect_screen.dart';
import 'golive_screen.dart';
import 'make_screen.dart';
import 'setup_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int tab = 0;
  final clipsKey = GlobalKey<ClipsScreenState>();

  void openSetup() => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SetupScreen()));

  Future<void> disconnect() async {
    await Api.instance.forget();
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const ConnectScreen()));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: RichText(
          text: const TextSpan(style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900, color: Neon.white), children: [
            TextSpan(text: 'Ninja Studio '),
            TextSpan(text: 'Clipping', style: TextStyle(color: Neon.pink)),
          ]),
        ),
        actions: [
          PopupMenuButton<String>(
            onSelected: (v) async {
              if (v == 'out') disconnect();
              if (v == 'studio') Engine.openUrl(Api.instance.base);
              if (v == 'stop') {
                final problem = await Engine.stop();
                if (context.mounted) toast(context, problem ?? 'Engine stopping…', bad: problem != null);
              }
              if (v == 'setup') openSetup();
            },
            itemBuilder: (_) => Api.instance.local
                ? const [
                    PopupMenuItem(enabled: false, child: Text('Engine: this phone')),
                    PopupMenuItem(value: 'studio', child: Text('Open the full studio (connect YouTube, logo…)')),
                    PopupMenuItem(value: 'setup', child: Text('Phone setup (Termux, engine, battery)')),
                    PopupMenuItem(value: 'stop', child: Text('Stop the engine')),
                    PopupMenuItem(value: 'out', child: Text('Use a PC instead')),
                    PopupMenuItem(enabled: false, child: Text(creditLine, style: TextStyle(fontSize: 11.5))),
                  ]
                : [
                    PopupMenuItem(enabled: false, child: Text('PC: ${Api.instance.base.replaceFirst('http://', '')}')),
                    const PopupMenuItem(value: 'out', child: Text('Disconnect from this PC')),
                    const PopupMenuItem(enabled: false, child: Text(creditLine, style: TextStyle(fontSize: 11.5))),
                  ],
          ),
        ],
      ),
      // IndexedStack keeps every tab alive, so a running Make or live keeps updating while you look at another tab.
      body: Column(children: [
        EngineBar(onSetup: openSetup),
        Expanded(
          child: IndexedStack(index: tab, children: [
            MakeScreen(onClipsChanged: () => clipsKey.currentState?.refresh()),
            ClipsScreen(key: clipsKey),
            const GoLiveScreen(),
          ]),
        ),
      ]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (i) {
          setState(() => tab = i);
          if (i == 1) clipsKey.currentState?.refresh();
        },
        destinations: const [
          NavigationDestination(icon: Icon(Icons.auto_awesome), label: 'Create'),
          NavigationDestination(icon: Icon(Icons.video_library_outlined), label: 'My clips'),
          NavigationDestination(icon: Icon(Icons.sensors), label: 'Go Live'),
        ],
      ),
    );
  }
}
