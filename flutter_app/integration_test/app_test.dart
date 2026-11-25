// Runs inside the real app on a phone / simulator against a running PC app with phone access on:
//   flutter test integration_test -d <device> --dart-define=PC=192.168.1.5:8770 --dart-define=PIN=123456
// Needs a PC data folder with at least 2 finished clips and no YouTube channel connected (it deletes one clip).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:ninja_studio/api.dart';
import 'package:ninja_studio/main.dart';
import 'package:ninja_studio/screens/golive_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:video_player/video_player.dart';

const pc = String.fromEnvironment('PC');
const pin = String.fromEnvironment('PIN');

Future<void> pumpUntil(WidgetTester t, Finder f, {int seconds = 25}) async {
  final end = DateTime.now().add(Duration(seconds: seconds));
  while (DateTime.now().isBefore(end)) {
    await t.pump(const Duration(milliseconds: 250));
    if (f.evaluate().isNotEmpty) return;
  }
  throw TestFailure('Timed out waiting for $f');
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('pair, make, my clips, play, upload, delete, go live', (t) async {
    expect(pc, isNotEmpty, reason: 'pass --dart-define=PC=<pc address>');
    final prefs = await SharedPreferences.getInstance();
    await prefs.clear();
    await Api.instance.load();
    await t.pumpWidget(const NinjaStudioApp());
    await t.pumpAndSettle();

    // 1. wrong PIN is refused, right PIN pairs
    await t.enterText(find.byKey(const Key('address')), pc);
    await t.enterText(find.byKey(const Key('pin')), '000001');
    await t.tap(find.byKey(const Key('connect')));
    await pumpUntil(t, find.text('Wrong PIN.'));
    await t.enterText(find.byKey(const Key('pin')), pin);
    await t.tap(find.byKey(const Key('connect')));
    await pumpUntil(t, find.text('Make clips'));

    // 2. Make needs a link
    await t.tap(find.byKey(const Key('make-go')));
    await pumpUntil(t, find.text('Paste a YouTube, Twitch or Kick link first.'));
    ScaffoldMessenger.of(t.element(find.byType(Scaffold).first)).clearSnackBars();

    // 3. My clips from the PC, with YouTube tags
    await t.tap(find.text('My clips'));
    await pumpUntil(t, find.textContaining('My clips ('));
    final before = int.parse(RegExp(r'\((\d+)\)').firstMatch((t.widget(find.textContaining('My clips (')) as Text).data!)!.group(1)!);
    expect(before, greaterThanOrEqualTo(2));
    expect(find.text('○ Not uploaded'), findsWidgets);

    // 4. play a clip straight from the PC (the PIN cookie is sent with the video request)
    await t.tap(find.byKey(const Key('clip-clip0001')));
    await pumpUntil(t, find.byType(VideoPlayer), seconds: 30);
    await t.pageBack();
    await t.pumpAndSettle();

    // 5. select → upload to YouTube (no channel connected on this PC, so the PC says so)
    await t.longPress(find.byKey(const Key('clip-clip0001')));
    await pumpUntil(t, find.text('1 selected'));
    await t.tap(find.byKey(const Key('upload-selected')));
    await pumpUntil(t, find.textContaining('not connected'));

    // 6. delete it from the PC
    await t.tap(find.byKey(const Key('delete-selected')));
    await pumpUntil(t, find.text('Yes'));
    await t.tap(find.text('Yes'));
    await pumpUntil(t, find.text('My clips (${before - 1})'));

    // 7. Go Live tab shows the channel state and needs a link
    await t.tap(find.text('Go Live'));
    await pumpUntil(t, find.textContaining('YouTube channel'));
    final page = find.descendant(of: find.byType(GoLiveScreen), matching: find.byType(Scrollable)).first;
    await t.scrollUntilVisible(find.byKey(const Key('live-go')), 300, scrollable: page);
    await t.tap(find.byKey(const Key('live-go')));
    await pumpUntil(t, find.text('Paste the link of the video to stream.'));
  });
}
