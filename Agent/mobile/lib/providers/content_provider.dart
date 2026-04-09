import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import '../config.dart';

class UploadedVideo {
  final String key;
  final String url;
  final String filename;
  final int size;

  UploadedVideo({
    required this.key,
    required this.url,
    required this.filename,
    required this.size,
  });
}

class ContentProvider extends ChangeNotifier {
  final List<UploadedVideo> _videos = [];
  bool _isUploading = false;
  String _uploadProgress = '';

  List<UploadedVideo> get videos => List.unmodifiable(_videos);
  bool get isUploading => _isUploading;
  String get uploadProgress => _uploadProgress;

  Future<void> loadVideos() async {
    try {
      final res = await http.get(Uri.parse(ApiConfig.videosEndpoint));
      if (res.statusCode == 200) {
        final List<dynamic> data = jsonDecode(res.body);
        _videos.clear();
        for (final v in data) {
          _videos.add(UploadedVideo(
            key: v['key'],
            url: v['url'],
            filename: v['key'].split('/').last,
            size: v['size'],
          ));
        }
        notifyListeners();
      }
    } catch (e) {
      debugPrint('Error loading videos: $e');
    }
  }

  Future<void> pickAndUploadVideos() async {
    final picker = ImagePicker();
    final List<XFile> pickedFiles = await picker.pickMultipleMedia();

    if (pickedFiles.isEmpty) return;

    _isUploading = true;
    notifyListeners();

    for (int i = 0; i < pickedFiles.length; i++) {
      final file = pickedFiles[i];
      _uploadProgress = 'Uploading ${i + 1}/${pickedFiles.length}: ${file.name}';
      notifyListeners();

      try {
        final request = http.MultipartRequest(
          'POST',
          Uri.parse(ApiConfig.uploadVideoEndpoint),
        );
        request.files.add(await http.MultipartFile.fromPath('file', file.path));
        final response = await request.send();
        final body = await response.stream.bytesToString();

        if (response.statusCode == 200) {
          final data = jsonDecode(body);
          _videos.add(UploadedVideo(
            key: data['key'],
            url: data['url'],
            filename: data['filename'] ?? file.name,
            size: data['size'],
          ));
        }
      } catch (e) {
        debugPrint('Error uploading ${file.name}: $e');
      }
    }

    _isUploading = false;
    _uploadProgress = '';
    notifyListeners();
  }
}
