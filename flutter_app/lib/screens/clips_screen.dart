import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../theme.dart';
import 'video_screen.dart';

/// Finished clips on the PC: play, save to the phone, upload to YouTube (one or many) and delete.
class ClipsScreen extends StatefulWidget {
  const ClipsScreen({super.key});

  @override
  State<ClipsScreen> createState() => ClipsScreenState();
}

class ClipsScreenState extends State<ClipsScreen> with AutomaticKeepAliveClientMixin {
  List<Map<String, dynamic>> clips = [];
  Map<String, dynamic> youtube = {};
  final selected = <String>{};
  bool loading = false;
  String? error;
  Timer? poll;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    refresh();
  }

  @override
  void dispose() {
    poll?.cancel();
    super.dispose();
  }

  Future<void> refresh() async {
    if (!mounted) return;
    setState(() => loading = true);
    try {
      final list = await Api.instance.getJson('/library') as List;
      clips = list.map((e) => Map<String, dynamic>.from(e)).toList();
      selected.removeWhere((id) => !clips.any((c) => c['id'] == id));
      error = null;
      await refreshTags();
    } catch (e) {
      error = e.toString();
    }
    if (mounted) setState(() => loading = false);
  }

  Future<void> refreshTags() async {
    try {
      youtube = Map<String, dynamic>.from(await Api.instance.getJson('/youtube/clip-states'));
    } catch (_) {}
    final busy = youtube.values.any((s) => s is Map && (s['status'] == 'queued' || s['status'] == 'uploading' || s['status'] == 'starting'));
    poll?.cancel();
    if (busy) {
      poll = Timer(const Duration(seconds: 3), () async {
        await refreshTags();
        if (mounted) setState(() {});
      });
    }
  }

  Widget tag(String id) {
    final s = youtube[id];
    final status = s is Map ? s['status'] : null;
    final (text, color) = switch (status) {
      'uploaded' => ('✓ On YouTube', Neon.green),
      'queued' => ('⏳ Waiting', Neon.amber),
      'starting' || 'uploading' => ('⏳ Uploading ${(((s as Map)['progress'] ?? 0) * 100).round()}%', Neon.amber),
      'error' => ('✕ Upload failed', Colors.redAccent),
      _ => ('○ Not uploaded', Neon.muted),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(border: Border.all(color: color.withValues(alpha: .5)), borderRadius: BorderRadius.circular(99)),
      child: Text(text, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w700)),
    );
  }

  Future<void> upload(List<String> ids) async {
    if (ids.isEmpty) return;
    final already = ids.where((id) => (youtube[id] is Map) && youtube[id]['status'] == 'uploaded').length;
    if (already > 0 && !await confirm('$already of these are already on YouTube. Upload them again?')) return;
    try {
      final items = ids.map((id) => {'clip_id': id, 'title': clips.firstWhere((c) => c['id'] == id)['title']}).toList();
      final r = await Api.instance.postJson('/youtube/upload-batch', {'items': items});
      final failed = (r['jobs'] as List).where((j) => j['error'] != null).length;
      if (mounted) toast(context, '${items.length - failed} clip(s) queued for YouTube. They upload one by one.');
      setState(selected.clear);
      await refreshTags();
      if (mounted) setState(() {});
    } catch (e) {
      if (mounted) toast(context, e, bad: true);
    }
  }

  Future<void> delete(List<String> ids) async {
    if (ids.isEmpty) return;
    if (!await confirm('${ids.length == 1 ? 'This clip' : '${ids.length} clips'} will be deleted from the PC. '
        'A video already on YouTube stays on YouTube.')) {
      return;
    }
    try {
      await Api.instance.postJson('/clips/delete', {'ids': ids});
      selected.removeAll(ids);
      await refresh();
      if (mounted) toast(context, 'Deleted.');
    } catch (e) {
      if (mounted) toast(context, e, bad: true);
    }
  }

  Future<bool> confirm(String text) async =>
      await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(content: Text(text), actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Yes')),
        ]),
      ) ??
      false;

  void open(Map<String, dynamic> c) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => VideoScreen(id: c['id'], title: '${c['title']}')));

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final selecting = selected.isNotEmpty;
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 8, 0),
        child: Row(children: [
          Expanded(
            child: Text(selecting ? '${selected.length} selected' : 'My clips (${clips.length})',
                style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900)),
          ),
          if (selecting) TextButton(onPressed: () => setState(selected.clear), child: const Text('Clear'))
          else if (clips.isNotEmpty)
            TextButton(onPressed: () => setState(() => selected.addAll(clips.map((c) => c['id'] as String))), child: const Text('Select all')),
          IconButton(tooltip: 'Refresh', onPressed: refresh, icon: const Icon(Icons.refresh)),
        ]),
      ),
      if (selecting)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
          child: Row(children: [
            Expanded(
              child: FilledButton.icon(
                key: const Key('upload-selected'),
                style: FilledButton.styleFrom(backgroundColor: const Color(0xFFCC0000), foregroundColor: Colors.white),
                onPressed: () => upload(selected.toList()),
                icon: const Icon(Icons.smart_display),
                label: const Text('Upload to YouTube'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                key: const Key('delete-selected'),
                style: OutlinedButton.styleFrom(foregroundColor: Colors.redAccent, side: const BorderSide(color: Colors.redAccent)),
                onPressed: () => delete(selected.toList()),
                icon: const Icon(Icons.delete_outline),
                label: const Text('Delete'),
              ),
            ),
          ]),
        ),
      Expanded(
        child: RefreshIndicator(
          onRefresh: refresh,
          child: error != null
              ? ListView(padding: const EdgeInsets.all(24), children: [Text(error!, style: const TextStyle(color: Color(0xFFFF7A90)))])
              : clips.isEmpty
                  ? ListView(padding: const EdgeInsets.all(24), children: [
                      Text(loading ? 'Loading…' : 'No clips yet. Make some in the Create tab.', style: const TextStyle(color: Neon.muted)),
                    ])
                  : ListView.builder(
                      padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                      itemCount: clips.length,
                      itemBuilder: (context, i) {
                        final c = clips[i];
                        final id = c['id'] as String;
                        final picked = selected.contains(id);
                        final seconds = ((c['meta'] ?? {})['duration'] ?? 0) as num;
                        final date = DateTime.fromMillisecondsSinceEpoch(((c['created'] ?? 0) as num).toInt() * 1000);
                        return Card(
                          key: Key('clip-$id'),
                          color: picked ? const Color(0xFF2A1F38) : null,
                          child: InkWell(
                            borderRadius: BorderRadius.circular(16),
                            onTap: () => selecting ? setState(() => picked ? selected.remove(id) : selected.add(id)) : open(c),
                            onLongPress: () => setState(() => picked ? selected.remove(id) : selected.add(id)),
                            child: Padding(
                              padding: const EdgeInsets.all(10),
                              child: Row(children: [
                                Container(
                                  width: 58, height: 92,
                                  decoration: BoxDecoration(
                                    borderRadius: BorderRadius.circular(10),
                                    gradient: const LinearGradient(colors: [Color(0xFF3A1230), Color(0xFF0F2A1A)], begin: Alignment.topLeft, end: Alignment.bottomRight),
                                  ),
                                  child: Icon(selecting ? (picked ? Icons.check_circle : Icons.radio_button_unchecked) : Icons.play_arrow_rounded,
                                      color: picked ? Neon.pink : Neon.cyan, size: 30),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                    Text('${c['title']}', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700)),
                                    const SizedBox(height: 4),
                                    Text('${seconds.toStringAsFixed(0)} s · ${date.day}/${date.month}/${date.year}', style: const TextStyle(color: Neon.muted, fontSize: 12)),
                                    const SizedBox(height: 6),
                                    tag(id),
                                  ]),
                                ),
                                PopupMenuButton<String>(
                                  onSelected: (v) {
                                    if (v == 'play') open(c);
                                    if (v == 'save') shareClip(context, id);
                                    if (v == 'yt') upload([id]);
                                    if (v == 'del') delete([id]);
                                  },
                                  itemBuilder: (_) => const [
                                    PopupMenuItem(value: 'play', child: Text('▶ Play')),
                                    PopupMenuItem(value: 'save', child: Text('⤓ Save / share to phone')),
                                    PopupMenuItem(value: 'yt', child: Text('▶ Upload to YouTube')),
                                    PopupMenuItem(value: 'del', child: Text('🗑 Delete')),
                                  ],
                                ),
                              ]),
                            ),
                          ),
                        );
                      },
                    ),
        ),
      ),
    ]);
  }
}
