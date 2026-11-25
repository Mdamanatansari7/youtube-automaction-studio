import 'package:flutter/material.dart';

// Same colours as the PC app.
class Neon {
  static const bg = Color(0xFF0A0A0C);
  static const panel = Color(0xFF151217);
  static const line = Color(0xFF2E2A31);
  static const pink = Color(0xFFFF4BA5);
  // pink + green palette (same as the website): "cyan" and "lime" are the green accents
  static const cyan = Color(0xFF4ADE80);
  static const lime = Color(0xFF86EFAC);
  static const white = Color(0xFFFBF6FF);
  static const muted = Color(0xFFA99DB7);
  static const red = Color(0xFFE11D48);
  static const green = Color(0xFF22C55E);
  static const amber = Color(0xFFF59E0B);

  static ThemeData theme() {
    final base = ThemeData(brightness: Brightness.dark, useMaterial3: true, colorSchemeSeed: pink);
    return base.copyWith(
      scaffoldBackgroundColor: bg,
      appBarTheme: const AppBarTheme(backgroundColor: bg, foregroundColor: white, elevation: 0, centerTitle: false),
      cardTheme: CardThemeData(
          color: panel,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: const BorderSide(color: line))),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFF0F0B18),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: line)),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: line)),
        labelStyle: const TextStyle(color: muted),
      ),
      navigationBarTheme: const NavigationBarThemeData(backgroundColor: panel, indicatorColor: Color(0x55FF4BA5)),
    );
  }
}

/// Shows an error or a message at the bottom of the screen.
void toast(BuildContext context, Object message, {bool bad = false}) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(message.toString()), backgroundColor: bad ? const Color(0xFF7F1D1D) : Neon.panel, duration: const Duration(seconds: 5)));
}

const layouts = <String, String>{
  'stack': 'Face + gameplay (finds the facecam)',
  'bottom': 'Gameplay + face below',
  'fill': 'Crop to fill the screen',
  'blur': 'Full video, blurred fill',
  'pip_tl': 'Facecam top-left',
  'pip_tr': 'Facecam top-right',
  'pip_bl': 'Facecam bottom-left',
  'pip_br': 'Facecam bottom-right',
  'circle': 'Circle facecam',
  'side': 'Side by side',
  'game': 'Gameplay only',
};

String clock(num seconds) {
  final s = seconds.floor().clamp(0, 1 << 30);
  final h = s ~/ 3600, m = (s ~/ 60) % 60, r = s % 60;
  return '$h:${m.toString().padLeft(2, '0')}:${r.toString().padLeft(2, '0')}';
}
