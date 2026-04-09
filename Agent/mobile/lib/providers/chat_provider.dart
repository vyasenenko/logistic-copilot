import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../config.dart';

class ChatMessage {
  final String role; // 'user' or 'assistant'
  final String content;
  final DateTime timestamp;

  ChatMessage({
    required this.role,
    required this.content,
    DateTime? timestamp,
  }) : timestamp = timestamp ?? DateTime.now();
}

class ChatProvider extends ChangeNotifier {
  final List<ChatMessage> _messages = [];
  String? _conversationId;
  bool _isLoading = false;
  String _currentTool = '';

  List<ChatMessage> get messages => List.unmodifiable(_messages);
  String? get conversationId => _conversationId;
  bool get isLoading => _isLoading;
  String get currentTool => _currentTool;

  void newConversation() {
    _messages.clear();
    _conversationId = null;
    _currentTool = '';
    _isLoading = false;
    notifyListeners();
  }

  Future<void> loadConversation(String convId) async {
    _conversationId = convId;
    _messages.clear();
    notifyListeners();

    try {
      final res = await http.get(
        Uri.parse('${ApiConfig.conversationsEndpoint}/$convId/messages'),
      );
      if (res.statusCode == 200) {
        final List<dynamic> data = jsonDecode(res.body);
        for (final msg in data) {
          _messages.add(ChatMessage(
            role: msg['role'],
            content: msg['content'],
          ));
        }
        notifyListeners();
      }
    } catch (e) {
      debugPrint('Error loading conversation: $e');
    }
  }

  Future<void> sendMessage(String text) async {
    if (text.trim().isEmpty || _isLoading) return;

    // Add user message
    _messages.add(ChatMessage(role: 'user', content: text));
    _isLoading = true;
    notifyListeners();

    // Add empty assistant message
    _messages.add(ChatMessage(role: 'assistant', content: ''));

    try {
      final request = http.Request('POST', Uri.parse(ApiConfig.chatEndpoint));
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode({
        'content': text,
        'conversation_id': _conversationId,
      });

      final response = await http.Client().send(request);
      final stream = response.stream.transform(utf8.decoder);

      String fullContent = '';

      await for (final chunk in stream) {
        final lines = chunk.split('\n');
        for (final line in lines) {
          if (!line.startsWith('data: ')) continue;

          try {
            final event = jsonDecode(line.substring(6));

            if (event['event'] == 'token') {
              fullContent += event['data'];
              _messages.last = ChatMessage(
                role: 'assistant',
                content: fullContent,
              );
              notifyListeners();
            } else if (event['event'] == 'tool_start') {
              _currentTool = event['data'];
              notifyListeners();
            } else if (event['event'] == 'tool_end') {
              _currentTool = '';
              notifyListeners();
            }

            // Capture conversation ID
            if (event['conversation_id'] != null && _conversationId == null) {
              _conversationId = event['conversation_id'];
            }
          } catch (_) {}
        }
      }
    } catch (e) {
      _messages.last = ChatMessage(
        role: 'assistant',
        content: 'Connection error: $e',
      );
    }

    _isLoading = false;
    _currentTool = '';
    notifyListeners();
  }
}
