import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:ninja_studio/api.dart';
import 'package:ninja_studio/screens/connect_screen.dart';
import 'package:ninja_studio/screens/setup_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:ninja_studio/theme.dart';

void main() {
  test('PC address is completed with http:// and the default port', () {
    expect(Api.normalise('192.168.1.5'), 'http://192.168.1.5:8770');
    expect(Api.normalise(' 192.168.1.5:8771 '), 'http://192.168.1.5:8771');
    expect(Api.normalise('http://10.0.0.2:9000/m'), 'http://10.0.0.2:9000');
  });

  test('clock shows h:mm:ss', () {
    expect(clock(0), '0:00:00');
    expect(clock(3725), '1:02:05');
  });

  testWidgets('phone setup lists the steps and waits for the required ones', (tester) async {
    SharedPreferences.setMockInitialValues({});
    tester.view.physicalSize = const Size(900, 2600);             // tall enough for every step
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(theme: Neon.theme(), home: const SetupScreen()));
    await tester.pump(const Duration(milliseconds: 300));
    for (final step in ['Termux app', 'Install the engine in Termux', 'Notifications', 'Keep Ninja Studio running', 'Keep Termux running (24 h lives)']) {
      expect(find.text(step), findsOneWidget);
    }
    expect(find.text('Install Termux'), findsOneWidget);        // no Termux here: its button shows
    final done = tester.widget<FilledButton>(find.ancestor(of: find.text('Finish the required steps first'), matching: find.byWidgetPredicate((w) => w is FilledButton)));
    expect(done.onPressed, isNull);
    await tester.pumpWidget(const SizedBox());                  // stops the screen's refresh timer
  });

  testWidgets('connect screen asks for the PC address and PIN', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: Neon.theme(), home: const ConnectScreen()));
    expect(find.text('PC address'), findsOneWidget);
    expect(find.text('6-digit PIN from the PC'), findsOneWidget);
    expect(find.text('Connect to my PC'), findsOneWidget);
    expect(find.textContaining('NEONCLIPPING_LAN=1 ./run.sh'), findsOneWidget);
  });
}
