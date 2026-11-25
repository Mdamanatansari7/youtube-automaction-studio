import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import 'video_screen.dart';

/// Paste a link → the PC finds the best moments and renders captioned 9:16 clips.
class MakeScreen extends StatefulWidget {
  const MakeScreen({super.key, this.onClipsChanged});
  final VoidCallback? onClipsChanged;

  @override
  State<MakeScreen> createState() => _MakeScreenState();
}

class _MakeScreenState extends State<MakeScreen> with AutomaticKeepAliveClientMixin {
  final link = TextEditingController();
  int count = 4;
  RangeValues length = const RangeValues(30, 60);
  String layout = Api.instance.local ? 'fill' : 'stack';     // the phone engine has no facecam finder (no OpenCV in Termux)
  String style = 'gta';
  bool autoYoutube = false;
  String? job;
  Map<String, dynamic> state = {};
  Timer? timer;

  static const styles = {'gta': 'GTA Neon', 'bold': 'Bold', 'clean': 'Clean', 'hormozi': 'Hormozi', 'mrbeast': 'MrBeast'};

  @override
  bool get wantKeepAlive => true;

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  bool get running => job != null && (state['status'] == null || state['status'] == 'running');

  Future<void> make() async {
    final url = link.text.trim();
    if (url.isEmpty) return toast(context, 'Paste a YouTube, Twitch or Kick link first.', bad: true);
    FocusScope.of(context).unfocus();
    try {
      final r = await Api.instance.postJson('/make', {
        'url': url, 'count': count, 'min_len': length.start.round(), 'max_len': length.end.round(),
        'layout': layout, 'caption_style': style, 'cam_auto': true, 'auto_youtube': autoYoutube,
      });
      setState(() {
        job = r['job'];
        state = {'status': 'running', 'stage': 'Starting', 'progress': 0};
      });
      timer?.cancel();
      timer = Timer.periodic(const Duration(seconds: 2), (_) => poll());
    } catch (e) {
      if (mounted) toast(context, e, bad: true);
    }
  }

  Future<void> poll() async {
    if (job == null) return;
    try {
      final s = Map<String, dynamic>.from(await Api.instance.getJson('/make/$job'));
      if (!mounted) return;
      final before = (state['clips'] as List?)?.length ?? 0;
      setState(() => state = s);
      if (((s['clips'] as List?)?.length ?? 0) != before) widget.onClipsChanged?.call();
      if (s['status'] != 'running') {
        timer?.cancel();
        if (s['status'] == 'done') toast(context, 'Clips ready. They are also in My clips.');
      }
    } catch (e) {
      timer?.cancel();
      if (mounted) toast(context, e, bad: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final clips = (state['clips'] as List?) ?? const [];
    final progress = (state['progress'] is num) ? (state['progress'] as num).toDouble().clamp(0.0, 1.0) : null;
    return ListView(padding: const EdgeInsets.all(16), children: [
      const Text('Make clips', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w900)),
      Text('Paste a link. ${Api.instance.local ? 'This phone' : 'The PC'} finds the best moments and makes captioned Shorts.',
          style: const TextStyle(color: Neon.muted)),
      const SizedBox(height: 16),
      TextField(
        key: const Key('make-link'),
        controller: link,
        keyboardType: TextInputType.url,
        autocorrect: false,
        decoration: InputDecoration(
          labelText: 'Video link',
          hintText: 'https://www.youtube.com/watch?v=…',
          suffixIcon: IconButton(icon: const Icon(Icons.clear), onPressed: link.clear),
        ),
      ),
      const SizedBox(height: 14),
      Text('Clips: $count', style: const TextStyle(fontWeight: FontWeight.w700)),
      Slider(value: count.toDouble(), min: 1, max: 12, divisions: 11, label: '$count', activeColor: Neon.pink, onChanged: (v) => setState(() => count = v.round())),
      Text('Length: ${length.start.round()}–${length.end.round()} s', style: const TextStyle(fontWeight: FontWeight.w700)),
      RangeSlider(values: length, min: 10, max: 180, divisions: 34, activeColor: Neon.pink,
          labels: RangeLabels('${length.start.round()} s', '${length.end.round()} s'), onChanged: (v) => setState(() => length = v)),
      DropdownButtonFormField<String>(
        initialValue: layout,
        decoration: const InputDecoration(labelText: 'Format'),
        items: layouts.entries.map((e) => DropdownMenuItem(value: e.key, child: Text(e.value))).toList(),
        onChanged: (v) => setState(() => layout = v ?? layout),
      ),
      const SizedBox(height: 12),
      DropdownButtonFormField<String>(
        initialValue: style,
        decoration: const InputDecoration(labelText: 'Caption style'),
        items: styles.entries.map((e) => DropdownMenuItem(value: e.key, child: Text(e.value))).toList(),
        onChanged: (v) => setState(() => style = v ?? style),
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        value: autoYoutube,
        activeThumbColor: Neon.pink,
        title: const Text('Upload each clip to YouTube when ready'),
        onChanged: (v) => setState(() => autoYoutube = v),
      ),
      const SizedBox(height: 6),
      FilledButton.icon(
        key: const Key('make-go'),
        onPressed: running ? null : make,
        style: FilledButton.styleFrom(backgroundColor: Neon.pink, foregroundColor: Colors.black, minimumSize: const Size.fromHeight(52)),
        icon: const Icon(Icons.bolt),
        label: Text(running ? 'Making clips…' : 'Make clips'),
      ),
      if (job != null) ...[
        const SizedBox(height: 18),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(state['status'] == 'error' ? '✕ Stopped' : state['status'] == 'done' ? '✓ Done' : '⏳ Working',
                  style: const TextStyle(fontWeight: FontWeight.w800)),
              const SizedBox(height: 6),
              Text('${state['error'] ?? state['stage'] ?? ''}', style: TextStyle(color: state['error'] != null ? const Color(0xFFFF7A90) : Neon.muted)),
              if (running) ...[const SizedBox(height: 10), LinearProgressIndicator(value: progress, color: Neon.pink)],
            ]),
          ),
        ),
      ],
      for (final c in clips)
        Card(
          child: ListTile(
            leading: Container(
              width: 46, height: 46,
              decoration: BoxDecoration(color: const Color(0xFF241C31), borderRadius: BorderRadius.circular(10)),
              child: Icon(c['error'] != null ? Icons.error_outline : Icons.play_arrow, color: c['error'] != null ? Colors.redAccent : Neon.cyan),
            ),
            title: Text('${c['title'] ?? 'Clip'}', maxLines: 2, overflow: TextOverflow.ellipsis),
            subtitle: Text(c['error'] != null ? 'Failed: ${c['error']}' : '🔥 ${c['viral'] ?? ''} · ${c['hook'] ?? ''}', maxLines: 2, overflow: TextOverflow.ellipsis),
            trailing: c['error'] == null ? IconButton(icon: const Icon(Icons.ios_share), onPressed: () => shareClip(context, c['file'])) : null,
            onTap: c['error'] == null
                ? () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => VideoScreen(id: c['file'], title: '${c['title'] ?? 'Clip'}')))
                : null,
          ),
        ),
    ]);
  }
}
