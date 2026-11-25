import 'dart:io';

import 'package:flutter/material.dart';

import '../api.dart';
import '../engine.dart';
import '../theme.dart';
import 'home_screen.dart';
import 'setup_screen.dart';

/// Pair the phone with the PC: the address and PIN are shown on the PC under Live clipping → Phone access.
class ConnectScreen extends StatefulWidget {
  const ConnectScreen({super.key});

  @override
  State<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends State<ConnectScreen> {
  final address = TextEditingController(text: Api.instance.base.replaceFirst('http://', ''));
  final pin = TextEditingController();
  bool busy = false;
  String? error;

  Future<void> useThisPhone() async {
    await Api.instance.useLocal();
    final done = await Engine.setupDone();
    if (!mounted) return;
    Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => done ? const HomeScreen() : const SetupScreen()));
  }

  Future<void> connect() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await Api.instance.login(address.text, pin.text);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => const HomeScreen()));
    } catch (e) {
      setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const SizedBox(height: 24),
            RichText(
              text: const TextSpan(style: TextStyle(fontSize: 30, fontWeight: FontWeight.w900, color: Neon.white), children: [
                TextSpan(text: 'Ninja Studio '),
                TextSpan(text: 'Clipping', style: TextStyle(color: Neon.pink)),
              ]),
            ),
            const SizedBox(height: 6),
            const Text('Make clips, upload to YouTube and go live from your phone.', style: TextStyle(color: Neon.muted)),
            const SizedBox(height: 20),
            if (Platform.isAndroid) ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Text('📱 This phone does the work', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w900)),
                    const SizedBox(height: 6),
                    const Text('No laptop needed: the engine runs on this phone (in Termux) and keeps going for 24 h lives.',
                        style: TextStyle(color: Neon.muted)),
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      key: const Key('use-phone'),
                      onPressed: useThisPhone,
                      style: FilledButton.styleFrom(backgroundColor: Neon.pink, foregroundColor: Colors.black, minimumSize: const Size.fromHeight(52)),
                      icon: const Icon(Icons.smartphone),
                      label: const Text('Use this phone'),
                    ),
                    const Text('Next: a short setup checks everything the engine needs and installs it.',
                        style: TextStyle(color: Neon.muted, fontSize: 12.5)),
                  ]),
                ),
              ),
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 14),
                child: Text('— or use a PC on the same Wi-Fi —', textAlign: TextAlign.center, style: TextStyle(color: Neon.muted)),
              ),
            ],
            TextField(
              key: const Key('address'),
              controller: address,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: const InputDecoration(labelText: 'PC address', hintText: '192.168.1.5:8770'),
            ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('pin'),
              controller: pin,
              keyboardType: TextInputType.number,
              maxLength: 6,
              obscureText: true,
              decoration: const InputDecoration(labelText: '6-digit PIN from the PC', counterText: ''),
              onSubmitted: (_) => connect(),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              key: const Key('connect'),
              onPressed: busy ? null : connect,
              style: FilledButton.styleFrom(backgroundColor: Neon.pink, foregroundColor: Colors.black, minimumSize: const Size.fromHeight(52)),
              icon: busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.link),
              label: Text(busy ? 'Connecting…' : 'Connect to my PC'),
            ),
            if (error != null)
              Padding(padding: const EdgeInsets.only(top: 12), child: Text(error!, style: const TextStyle(color: Color(0xFFFF7A90)))),
            const SizedBox(height: 24),
            const Card(
              child: Padding(
                padding: EdgeInsets.all(16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('How to pair', style: TextStyle(fontWeight: FontWeight.w800)),
                  SizedBox(height: 8),
                  Text('1. Phone and PC on the same Wi-Fi.\n'
                      '2. On the PC start the app with phone access:\n'
                      '    Mac:  NEONCLIPPING_LAN=1 ./run.sh\n'
                      '    Windows: the “phone access” shortcut\n'
                      '3. On the PC open Create clips → Live clipping → Phone access. It shows the address and the PIN.\n'
                      '4. Type both here.', style: TextStyle(color: Neon.muted, height: 1.45)),
                ]),
              ),
            ),
            const SizedBox(height: 18),
            const Text(creditLine, textAlign: TextAlign.center, style: TextStyle(color: Neon.muted, fontSize: 12)),
          ],
        ),
      ),
    );
  }
}
