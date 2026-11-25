import 'package:flutter/material.dart';

import 'api.dart';
import 'engine.dart';
import 'screens/connect_screen.dart';
import 'screens/home_screen.dart';
import 'screens/setup_screen.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.instance.load();
  // "This phone" opens the setup the first time (Termux, the engine, battery), afterwards straight into the app.
  final setup = Api.instance.local && !await Engine.setupDone();
  runApp(NinjaStudioApp(setup: setup));
}

class NinjaStudioApp extends StatelessWidget {
  const NinjaStudioApp({super.key, this.setup = false});
  final bool setup;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Ninja Studio',
      debugShowCheckedModeBanner: false,
      theme: Neon.theme(),
      home: !Api.instance.paired
          ? const ConnectScreen()
          : setup
              ? const SetupScreen()
              : const HomeScreen(),
    );
  }
}
