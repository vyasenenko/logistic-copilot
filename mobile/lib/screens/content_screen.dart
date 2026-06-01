import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/chat_provider.dart';
import '../providers/content_provider.dart';

class ContentScreen extends StatefulWidget {
  const ContentScreen({super.key});

  @override
  State<ContentScreen> createState() => _ContentScreenState();
}

class _ContentScreenState extends State<ContentScreen> {
  @override
  void initState() {
    super.initState();
    // Load existing videos on screen open
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ContentProvider>().loadVideos();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Content Creator', style: TextStyle(fontSize: 16)),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // --- Carousel Section ---
            _SectionCard(
              icon: Icons.view_carousel,
              title: 'Carousel',
              subtitle: 'Create Instagram carousel with text slides',
              onTap: () => _createCarousel(context),
            ),

            const SizedBox(height: 16),

            // --- Video Section ---
            _SectionCard(
              icon: Icons.video_library,
              title: 'Video with Voiceover',
              subtitle: 'Combine your clips + AI voice narration',
              onTap: () => _createVideo(context),
            ),

            const SizedBox(height: 24),

            // --- Upload Section ---
            const Text('Your Video Clips',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
            const SizedBox(height: 12),

            Consumer<ContentProvider>(
              builder: (context, content, _) {
                if (content.isUploading) {
                  return Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Row(
                        children: [
                          const SizedBox(
                            width: 20, height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          ),
                          const SizedBox(width: 12),
                          Text(content.uploadProgress,
                              style: const TextStyle(color: Color(0xFF888888))),
                        ],
                      ),
                    ),
                  );
                }

                if (content.videos.isEmpty) {
                  return Card(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        children: [
                          const Icon(Icons.cloud_upload_outlined,
                              size: 48, color: Color(0xFF666666)),
                          const SizedBox(height: 12),
                          const Text('No clips uploaded yet',
                              style: TextStyle(color: Color(0xFF888888))),
                          const SizedBox(height: 12),
                          ElevatedButton.icon(
                            onPressed: () => content.pickAndUploadVideos(),
                            icon: const Icon(Icons.add),
                            label: const Text('Upload Clips'),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: const Color(0xFF3B82F6),
                              foregroundColor: Colors.white,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  );
                }

                return Column(
                  children: [
                    ...content.videos.map((v) => Card(
                      child: ListTile(
                        leading: const Icon(Icons.videocam,
                            color: Color(0xFF3B82F6)),
                        title: Text(v.filename,
                            style: const TextStyle(fontSize: 14)),
                        subtitle: Text(
                          '${(v.size / (1024 * 1024)).toStringAsFixed(1)} MB',
                          style: const TextStyle(
                              color: Color(0xFF888888), fontSize: 12),
                        ),
                      ),
                    )),
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                      onPressed: () => content.pickAndUploadVideos(),
                      icon: const Icon(Icons.add),
                      label: const Text('Add More Clips'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: const Color(0xFF3B82F6),
                        side: const BorderSide(color: Color(0xFF3B82F6)),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }

  void _createCarousel(BuildContext context) {
    _showTopicDialog(
      context,
      title: 'Create Carousel',
      hint: 'e.g., 7 productivity tips',
      onSubmit: (topic) {
        final chat = context.read<ChatProvider>();
        chat.sendMessage(
          'Create an Instagram carousel on the topic: "$topic". '
          'Generate slide content and use the create_carousel tool.',
        );
        // Switch to chat tab to see result
        _switchToChat(context);
      },
    );
  }

  void _createVideo(BuildContext context) {
    final videos = context.read<ContentProvider>().videos;
    if (videos.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Upload video clips first!'),
          backgroundColor: Color(0xFFE94560),
        ),
      );
      return;
    }

    _showTopicDialog(
      context,
      title: 'Create Video',
      hint: 'e.g., 5 habits of successful people',
      onSubmit: (topic) {
        final chat = context.read<ChatProvider>();
        chat.sendMessage(
          'Create a video on the topic: "$topic". '
          'Write a script, voice it with ElevenLabs, and assemble the video from my uploaded clips. '
          'Use the create_video_with_voiceover tools.',
        );
        _switchToChat(context);
      },
    );
  }

  void _switchToChat(BuildContext context) {
    // Navigate to chat tab (index 0)
    final homeState = context.findAncestorStateOfType<State>();
    if (homeState != null && homeState is dynamic) {
      // Simple approach: pop if pushed, or use callback
      Navigator.of(context).popUntil((route) => route.isFirst);
    }
  }

  void _showTopicDialog(
    BuildContext context, {
    required String title,
    required String hint,
    required Function(String) onSubmit,
  }) {
    final controller = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1A1A1A),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Text(title),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: InputDecoration(hintText: hint),
          maxLines: 3,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              if (controller.text.trim().isNotEmpty) {
                Navigator.pop(ctx);
                onSubmit(controller.text.trim());
              }
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF3B82F6),
              foregroundColor: Colors.white,
            ),
            child: const Text('Create'),
          ),
        ],
      ),
    );
  }
}

class _SectionCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  const _SectionCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Row(
            children: [
              Container(
                width: 56, height: 56,
                decoration: BoxDecoration(
                  color: const Color(0xFF3B82F6).withOpacity(0.15),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(icon, color: const Color(0xFF3B82F6), size: 28),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title,
                        style: const TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 4),
                    Text(subtitle,
                        style: const TextStyle(
                            fontSize: 13, color: Color(0xFF888888))),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: Color(0xFF666666)),
            ],
          ),
        ),
      ),
    );
  }
}
