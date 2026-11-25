import 'package:flutter/material.dart';
import 'package:share_plus/share_plus.dart';
import 'package:video_player/video_player.dart';

import '../api.dart';
import '../theme.dart';

/// Plays a clip straight from the PC.
class VideoScreen extends StatefulWidget {
  const VideoScreen({super.key, required this.id, required this.title});
  final String id;
  final String title;

  @override
  State<VideoScreen> createState() => _VideoScreenState();
}

class _VideoScreenState extends State<VideoScreen> {
  late final VideoPlayerController player;
  String? error;

  @override
  void initState() {
    super.initState();
    player = VideoPlayerController.networkUrl(Api.instance.media(widget.id), httpHeaders: Api.instance.headers)
      ..setLooping(true)
      ..initialize().then((_) {
        if (mounted) setState(() {});
        player.play();
      }).catchError((Object e) {
        if (mounted) setState(() => error = 'Could not play this clip: $e');
      });
  }

  @override
  void dispose() {
    player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final ready = player.value.isInitialized;
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        title: Text(widget.title, maxLines: 1, overflow: TextOverflow.ellipsis),
        actions: [IconButton(tooltip: 'Save / share', icon: const Icon(Icons.ios_share), onPressed: () => shareClip(context, widget.id))],
      ),
      body: Center(
        child: error != null
            ? Padding(padding: const EdgeInsets.all(24), child: Text(error!, style: const TextStyle(color: Neon.muted)))
            : !ready
                ? const CircularProgressIndicator()
                : GestureDetector(
                    onTap: () => setState(() => player.value.isPlaying ? player.pause() : player.play()),
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Flexible(child: AspectRatio(aspectRatio: player.value.aspectRatio, child: VideoPlayer(player))),
                      VideoProgressIndicator(player, allowScrubbing: true, colors: const VideoProgressColors(playedColor: Neon.pink)),
                    ]),
                  ),
      ),
    );
  }
}

/// Downloads the clip to the phone and opens the share sheet (choose "Save video" to keep it in the gallery).
Future<void> shareClip(BuildContext context, String id) async {
  final messenger = ScaffoldMessenger.of(context);
  messenger.showSnackBar(const SnackBar(content: Text('Getting the clip from the PC…'), duration: Duration(seconds: 2)));
  try {
    final file = await Api.instance.download(id);
    await SharePlus.instance.share(ShareParams(files: [XFile(file.path, mimeType: 'video/mp4')], text: 'Made with Ninja Studio Clipping'));
  } catch (e) {
    messenger.showSnackBar(SnackBar(content: Text(e.toString())));
  }
}
