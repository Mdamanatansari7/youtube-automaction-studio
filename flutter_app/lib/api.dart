// Talks to Ninja Studio Clipping on the PC over the home Wi-Fi.
// All heavy work (download, captions, rendering, live streaming) runs on the PC; this app is the remote and viewer.
// Pairing uses the 6-digit PIN shown on the PC; the PC answers with a cookie that is sent with every request.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ApiException implements Exception {
  ApiException(this.message, [this.status = 0]);
  final String message;
  final int status;
  @override
  String toString() => message;
}

class Api {
  Api._();
  static final Api instance = Api._();

  String base = ''; // e.g. http://192.168.1.5:8770
  String cookie = '';
  bool local = false; // "This phone": the engine runs in Termux on this phone (127.0.0.1, no PIN needed)
  final http.Client _client = http.Client();

  static const localBase = 'http://127.0.0.1:8770';
  bool get paired => base.isNotEmpty && (local || cookie.isNotEmpty);

  /// Use the engine on this phone. Works even while the engine is still off (the app can start it).
  Future<void> useLocal() async {
    local = true;
    base = localBase;
    cookie = '';
    await _save();
  }

  /// True when the engine answers.
  Future<bool> healthy() async => await engineVersion() != null;

  /// The running engine's version ('' for an engine too old to say), or null when it does not answer.
  Future<String?> engineVersion() async {
    try {
      final r = await _client.get(Uri.parse('$base/healthz'), headers: headers).timeout(const Duration(seconds: 3));
      if (r.statusCode != 200) return null;
      final j = jsonDecode(r.body);
      return j is Map ? (j['version'] ?? '').toString() : '';
    } catch (_) {
      return null;
    }
  }
  Map<String, String> get headers => {if (cookie.isNotEmpty) 'cookie': 'nc_phone=$cookie'};

  /// "192.168.1.5" or "192.168.1.5:8771" or "http://..." -> "http://192.168.1.5:8770"
  static String normalise(String input) {
    var s = input.trim();
    if (s.isEmpty) return s;
    if (!s.startsWith('http://') && !s.startsWith('https://')) s = 'http://$s';
    final u = Uri.parse(s);
    final port = u.hasPort ? u.port : 8770;
    return '${u.scheme}://${u.host}:$port';
  }

  Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    base = p.getString('base') ?? '';
    cookie = p.getString('cookie') ?? '';
    local = p.getBool('local') ?? false;
  }

  Future<void> _save() async {
    final p = await SharedPreferences.getInstance();
    await p.setString('base', base);
    await p.setString('cookie', cookie);
    await p.setBool('local', local);
  }

  Future<void> forget() async {
    cookie = '';
    local = false;
    final p = await SharedPreferences.getInstance();
    await p.remove('cookie');
    await p.setBool('local', false);
  }

  Future<void> login(String address, String pin) async {
    local = false;
    base = normalise(address);
    if (base.isEmpty) throw ApiException('Type the PC address shown on the PC.');
    final r = await _guard(() => _client.post(Uri.parse('$base/m/login'),
        headers: {'content-type': 'application/json'}, body: jsonEncode({'pin': pin.trim()})));
    if (r.statusCode != 200) _decode(r);
    final m = RegExp(r'nc_phone=([^;]+)').firstMatch(r.headers['set-cookie'] ?? '');
    if (m == null) throw ApiException('The PC did not accept the pairing. Update the PC app and try again.');
    cookie = m.group(1)!;
    await getJson('/library'); // proves the pairing really works
    await _save();
  }

  Future<dynamic> getJson(String path) async =>
      _decode(await _guard(() => _client.get(Uri.parse('$base$path'), headers: headers)));

  Future<dynamic> postJson(String path, [Object? body]) async => _decode(await _guard(() => _client.post(
      Uri.parse('$base$path'),
      headers: {...headers, 'content-type': 'application/json'},
      body: jsonEncode(body ?? {}))));

  Uri media(String id) => Uri.parse('$base/media/$id');

  /// Downloads a finished clip into the app's temporary folder (for Save / Share).
  Future<File> download(String id) async {
    final req = http.Request('GET', media(id))..headers.addAll(headers);
    final res = await _guard(() => _client.send(req), seconds: 30);
    if (res.statusCode != 200) throw ApiException('Could not download the clip (${res.statusCode}).', res.statusCode);
    final dir = await getTemporaryDirectory();
    final file = File('${dir.path}/ninjastudio-$id.mp4');
    final sink = file.openWrite();
    await res.stream.pipe(sink);
    return file;
  }

  Future<T> _guard<T>(Future<T> Function() send, {int seconds = 20}) async {
    try {
      return await send().timeout(Duration(seconds: seconds));
    } on SocketException {
      if (local) throw ApiException('The engine on this phone is not running. Press “Start engine” at the top.');
      throw ApiException('Cannot reach the PC at $base. The phone and the PC must be on the same Wi-Fi, '
          'and the PC app must be running with phone access.');
    } on TimeoutException {
      throw ApiException('The PC at $base did not answer. Check the Wi-Fi and that the PC app is running.');
    } on http.ClientException catch (e) {
      throw ApiException('Connection problem: ${e.message}');
    }
  }

  dynamic _decode(http.Response r) {
    dynamic j;
    try {
      j = jsonDecode(utf8.decode(r.bodyBytes));
    } catch (_) {
      j = null;
    }
    if (r.statusCode >= 400) {
      final detail = (j is Map && j['detail'] != null) ? j['detail'].toString() : 'The PC answered ${r.statusCode}.';
      if (r.statusCode == 403 && detail.contains('Phone access is off')) {
        throw ApiException('Phone access is off on the PC. Start the PC app with phone access '
            '(Mac: NEONCLIPPING_LAN=1 ./run.sh).', 403);
      }
      if (r.statusCode == 401 && detail.startsWith('Enter the PIN')) {
        throw ApiException('Pair again: enter the PIN shown on the PC.', 401);    // pairing missing or the PIN was changed on the PC
      }
      throw ApiException(detail, r.statusCode);
    }
    return j;
  }
}
