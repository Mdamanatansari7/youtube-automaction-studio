import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

import '../api.dart';
import '../theme.dart';
import 'video_screen.dart';

/// Stream a video live from the PC to your YouTube channel (or any RTMP server) as a Shorts or landscape live.
class GoLiveScreen extends StatefulWidget {
  const GoLiveScreen({super.key});

  @override
  State<GoLiveScreen> createState() => _GoLiveScreenState();
}

class _GoLiveScreenState extends State<GoLiveScreen> with AutomaticKeepAliveClientMixin {
  final link = TextEditingController();
  final title = TextEditingController(text: '🔴 LIVE');
  final banner = TextEditingController();
  String shape = 'shorts';
  String layout = Api.instance.local ? 'fill' : 'stack';
  double crop = 50;
  bool loop = true;
  String privacy = 'public';
  String bannerBg = '#ff4ba5';
  bool showBanner = true;
  bool showLogo = true;
  Map<String, dynamic> lastOverlay = {};
  Map<String, dynamic>? yt;
  String? liveId;
  Map<String, dynamic> live = {};
  Timer? timer;
  bool starting = false;

  static const colours = ['#ff4ba5', '#e11d48', '#f59e0b', '#22c55e', '#2563eb', '#111111'];
  static const runningStates = ['starting', 'downloading', 'connecting', 'live', 'reconnecting', 'testing'];

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final last = Map<String, dynamic>.from(await Api.instance.getJson('/golive-last'));
      if (last.isNotEmpty) {
        shape = last['format'] ?? shape;
        layout = (last['layout'] == 'game' ? 'fill' : last['layout']) ?? layout;   // a crop is saved as its game window
        if (!layouts.containsKey(layout)) layout = 'stack';
        crop = ((last['crop'] ?? .5) as num).toDouble() * 100;
        loop = last['loop'] ?? loop;
        privacy = last['privacy'] ?? privacy;
        if ((last['title'] ?? '').toString().isNotEmpty) title.text = last['title'];
        lastOverlay = Map<String, dynamic>.from(last['overlay'] ?? {});
        banner.text = lastOverlay['banner_text'] ?? '';
        bannerBg = lastOverlay['banner_bg'] ?? bannerBg;
      }
    } catch (_) {}
    try {
      yt = Map<String, dynamic>.from(await Api.instance.getJson('/youtube/status'));
    } catch (_) {}
    try {
      final a = await Api.instance.getJson('/golive-active');
      if (a['live'] != null) attach(a['live']);
    } catch (_) {}
    if (mounted) setState(() {});
  }

  /// Where the one-time YouTube settings are done: the PC, or the full studio in this phone's browser.
  String where() => Api.instance.local ? 'Menu ⋮ → Open the full studio' : 'On the PC';

  Map<String, dynamic> overlay() => {
        'banner_text': banner.text.trim(), 'banner_bg': bannerBg, 'banner_color': lastOverlay['banner_color'] ?? '#ffffff',
        'banner_pos': lastOverlay['banner_pos'] ?? 'bottom', 'show_banner': showBanner,
        'logo': lastOverlay['logo'] ?? '', 'logo_pos': lastOverlay['logo_pos'] ?? 'tr', 'logo_size': lastOverlay['logo_size'] ?? 18,
        'banner_image': lastOverlay['banner_image'] ?? '', 'show_logo': showLogo,
      };

  Future<void> start(bool test) async {
    final url = link.text.trim();
    if (url.isEmpty) return toast(context, 'Paste the link of the video to stream.', bad: true);
    if (!test) {
      if (yt == null || yt!['connected'] != true) return toast(context, 'Connect your YouTube channel first: ${where()} → ▶ Connect YouTube.', bad: true);
      if (yt!['live_allowed'] != true) return toast(context, '${where()} → Go Live → press “Allow live streaming” once.', bad: true);
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Go live now?'),
          content: Text('On ${yt?['channel']?['title'] ?? 'your channel'} as ${privacy[0].toUpperCase()}${privacy.substring(1)}.\n\n'
              'Only stream videos you own or have permission to use, or YouTube can strike your channel.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
            FilledButton(style: FilledButton.styleFrom(backgroundColor: Neon.red), onPressed: () => Navigator.pop(c, true), child: const Text('Go live')),
          ],
        ),
      );
      if (ok != true || !mounted) return;
    }
    FocusScope.of(context).unfocus();
    setState(() => starting = true);
    try {
      final r = await Api.instance.postJson('/golive/start', {
        'url': url, 'test': test, 'format': shape, 'quality': 1080, 'fps': 30, 'layout': layout, 'crop': crop.round(),
        'loop': loop, 'cam_auto': true, 'platform': 'youtube_auto', 'title': title.text.trim(), 'privacy': privacy, ...overlay(),
      });
      attach(r['live']);
    } catch (e) {
      if (mounted) toast(context, e, bad: true);
    } finally {
      if (mounted) setState(() => starting = false);
    }
  }

  void attach(String id) {
    setState(() {
      liveId = id;
      live = {};
    });
    timer?.cancel();
    timer = Timer.periodic(const Duration(seconds: 1), (_) => poll());
    poll();
  }

  Future<void> poll() async {
    if (liveId == null) return;
    try {
      final s = Map<String, dynamic>.from(await Api.instance.getJson('/golive/$liveId'));
      if (!mounted) return;
      setState(() => live = s);
      if (!runningStates.contains(s['status'])) timer?.cancel();
    } catch (e) {
      timer?.cancel();
      if (mounted) toast(context, e, bad: true);
    }
  }

  Future<void> updateOverlay() async {
    try {
      await Api.instance.postJson('/golive/$liveId/overlay', overlay());
      if (mounted) toast(context, 'Banner updated. Viewers see it in a few seconds.');
    } catch (e) {
      if (mounted) toast(context, e, bad: true);
    }
  }

  Future<void> stop() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(content: const Text('Stop now?'), actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('No')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Stop')),
      ]),
    );
    if (ok != true) return;
    try {
      await Api.instance.postJson('/golive/$liveId/stop');
    } catch (e) {
      if (mounted) toast(context, e, bad: true);
    }
    poll();
  }

  String label(String? status) => switch (status) {
        'starting' => '⏳ Preparing…',
        'downloading' => '⬇ Downloading the video…',
        'connecting' => '⏳ Connecting…',
        'live' => '🔴 LIVE',
        'reconnecting' => '⚠ Reconnecting…',
        'testing' => '🧪 Test running…',
        'done' => '✓ Finished',
        'stopped' => '■ Stopped',
        'error' => '✕ Stopped with an error',
        _ => '…',
      };

  Widget manage() {
    final s = live;
    final running = runningStates.contains(s['status']);
    final stats = <String>[
      if ((s['stage'] ?? '').toString().isNotEmpty) s['stage'],
      if (s['facecam'] != null && s['facecam'] != '') s['facecam'],
      if ((s['frames'] ?? 0) > 0) 'video at ${clock(s['position'] ?? 0)}${(s['duration'] ?? 0) > 0 ? ' / ${clock(s['duration'])}' : ''}',
      if ((s['fps'] ?? 0) > 0) '${(s['fps'] as num).round()} fps',
      if ((s['reconnects'] ?? 0) > 0) '${s['reconnects']} reconnects',
    ];
    return Card(
      key: const Key('live-card'),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${label(s['status'])}${s['status'] == 'live' ? ' · ${clock(s['elapsed'] ?? 0)}' : ''}',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w900, color: s['status'] == 'live' ? const Color(0xFFFF4D6D) : Neon.white)),
          const SizedBox(height: 6),
          Text(stats.join(' · '), style: const TextStyle(color: Neon.muted)),
          if (s['error'] != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text('${s['error']}', style: const TextStyle(color: Color(0xFFFF7A90)))),
          if (s['watch_url'] != null)
            Wrap(spacing: 8, children: [
              TextButton.icon(
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: s['watch_url']));
                  toast(context, 'Live link copied.');
                },
                icon: const Icon(Icons.copy, size: 18),
                label: const Text('Copy live link'),
              ),
              TextButton.icon(
                onPressed: () => SharePlus.instance.share(ShareParams(text: s['watch_url'])),
                icon: const Icon(Icons.share, size: 18),
                label: const Text('Share'),
              ),
            ]),
          if (s['status'] == 'done' && s['preview'] != null)
            FilledButton.icon(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => VideoScreen(id: s['preview'].toString().split('/').last, title: 'Test preview'))),
              icon: const Icon(Icons.play_arrow),
              label: const Text('Play the 15 s test'),
            ),
          const SizedBox(height: 8),
          Row(children: [
            if (running && s['test'] != true)
              Expanded(child: OutlinedButton.icon(onPressed: updateOverlay, icon: const Icon(Icons.edit), label: const Text('Update banner'))),
            if (running && s['test'] != true) const SizedBox(width: 10),
            if (running)
              Expanded(
                child: OutlinedButton.icon(
                  key: const Key('live-stop'),
                  style: OutlinedButton.styleFrom(foregroundColor: Colors.redAccent, side: const BorderSide(color: Colors.redAccent)),
                  onPressed: stop,
                  icon: const Icon(Icons.stop),
                  label: const Text('Stop'),
                ),
              )
            else
              Expanded(child: OutlinedButton(onPressed: () => setState(() => liveId = null), child: const Text('← Set up a new live'))),
          ]),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final running = liveId != null && runningStates.contains(live['status']);
    final ready = yt != null && yt!['connected'] == true && yt!['live_allowed'] == true;
    return ListView(padding: const EdgeInsets.all(16), children: [
      const Text('🔴 Go Live', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w900)),
      Text('Paste a video link. ${Api.instance.local ? 'This phone' : 'The PC'} downloads it and streams it live to your YouTube channel.',
          style: const TextStyle(color: Neon.muted)),
      const SizedBox(height: 10),
      Card(
        child: ListTile(
          leading: Icon(ready ? Icons.check_circle : Icons.info_outline, color: ready ? Neon.green : Neon.amber),
          title: Text(ready
              ? 'Ready on ${yt?['channel']?['title'] ?? 'your channel'}'
              : yt == null || yt!['connected'] != true
                  ? 'No YouTube channel connected yet (${where()} → ▶ Connect YouTube)'
                  : '${where()} → Go Live → press “Allow live streaming” once'),
          subtitle: const Text('No stream key needed: the live is created on your channel automatically.'),
          trailing: IconButton(icon: const Icon(Icons.refresh), onPressed: load),
        ),
      ),
      if (liveId != null) manage(),
      if (!running) ...[
        const SizedBox(height: 8),
        TextField(
          key: const Key('live-link'),
          controller: link,
          keyboardType: TextInputType.url,
          autocorrect: false,
          decoration: const InputDecoration(labelText: 'Video link to stream', hintText: 'https://www.youtube.com/watch?v=…'),
        ),
        const SizedBox(height: 12),
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'shorts', label: Text('Shorts 9:16'), icon: Icon(Icons.stay_current_portrait)),
            ButtonSegment(value: 'landscape', label: Text('Landscape 16:9'), icon: Icon(Icons.stay_current_landscape)),
          ],
          selected: {shape},
          onSelectionChanged: (v) => setState(() => shape = v.first),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: layout,
          decoration: const InputDecoration(labelText: 'Format'),
          items: layouts.entries.map((e) => DropdownMenuItem(value: e.key, child: Text(e.value))).toList(),
          onChanged: (v) => setState(() => layout = v ?? layout),
        ),
        if (layout == 'fill') ...[
          const SizedBox(height: 8),
          Text('Crop position: ${crop <= 10 ? 'Left' : crop >= 90 ? 'Right' : crop == 50 ? 'Centre' : '${crop.round()}%'}'),
          Slider(value: crop, min: 0, max: 100, divisions: 20, activeColor: Neon.pink, onChanged: (v) => setState(() => crop = v)),
        ] else
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
                Api.instance.local
                    ? '🙂 Face layouts need the facecam finder, which only the PC engine has. On this phone the video fills the screen.'
                    : '🙂 The PC finds the facecam in the video by itself. Without a facecam it fills the screen.',
                style: const TextStyle(color: Neon.muted, fontSize: 12)),
          ),
        SwitchListTile(contentPadding: EdgeInsets.zero, value: loop, activeThumbColor: Neon.pink, title: const Text('Loop the video (keep the live going)'),
            onChanged: (v) => setState(() => loop = v)),
        TextField(controller: title, maxLength: 100, decoration: const InputDecoration(labelText: 'Live title')),
        DropdownButtonFormField<String>(
          initialValue: privacy,
          decoration: const InputDecoration(labelText: 'Who can watch'),
          items: const [
            DropdownMenuItem(value: 'public', child: Text('Public')),
            DropdownMenuItem(value: 'unlisted', child: Text('Unlisted (only with the link)')),
            DropdownMenuItem(value: 'private', child: Text('Private (only you)')),
          ],
          onChanged: (v) => setState(() => privacy = v ?? privacy),
        ),
      ],
      const SizedBox(height: 14),
      const Text('Banner & logo', style: TextStyle(fontWeight: FontWeight.w800)),
      const SizedBox(height: 8),
      TextField(key: const Key('live-banner'), controller: banner, maxLength: 120, decoration: const InputDecoration(labelText: 'Banner text', hintText: 'LIVE NOW · Follow @amanat__official_')),
      Wrap(spacing: 10, children: [
        for (final c in colours)
          GestureDetector(
            onTap: () => setState(() => bannerBg = c),
            child: CircleAvatar(
              radius: 16,
              backgroundColor: Color(int.parse('FF${c.substring(1)}', radix: 16)),
              child: bannerBg == c ? const Icon(Icons.check, size: 18, color: Colors.white) : null,
            ),
          ),
      ]),
      SwitchListTile(contentPadding: EdgeInsets.zero, value: showBanner, activeThumbColor: Neon.pink, title: const Text('Show banner'),
          onChanged: (v) => setState(() => showBanner = v)),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        value: showLogo,
        activeThumbColor: Neon.pink,
        title: const Text('Show my logo'),
        subtitle: Text((lastOverlay['logo'] ?? '').toString().isNotEmpty
                ? 'The logo from your last live in the full studio'
                : 'Set a logo once in Go Live (${where().replaceFirst('On the PC', 'on the PC')})',
            style: const TextStyle(fontSize: 12)),
        onChanged: (v) => setState(() => showLogo = v),
      ),
      if (!running)
        Row(children: [
          Expanded(
            child: OutlinedButton.icon(
              key: const Key('live-test'),
              onPressed: starting ? null : () => start(true),
              icon: const Icon(Icons.science_outlined),
              label: const Text('Test 15 s'),
              style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(50)),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: FilledButton.icon(
              key: const Key('live-go'),
              onPressed: starting ? null : () => start(false),
              icon: const Icon(Icons.sensors),
              label: const Text('Go live'),
              style: FilledButton.styleFrom(backgroundColor: Neon.red, foregroundColor: Colors.white, minimumSize: const Size.fromHeight(50)),
            ),
          ),
        ]),
      const SizedBox(height: 30),
    ]);
  }
}
