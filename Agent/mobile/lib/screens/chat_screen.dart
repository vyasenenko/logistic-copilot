import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:provider/provider.dart';
import '../providers/chat_provider.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<ChatProvider>(
      builder: (context, chat, _) {
        _scrollToBottom();

        return Scaffold(
          appBar: AppBar(
            title: const Text('AI Agent', style: TextStyle(fontSize: 16)),
            actions: [
              IconButton(
                icon: const Icon(Icons.add),
                onPressed: () => chat.newConversation(),
                tooltip: 'New chat',
              ),
            ],
          ),
          body: Column(
            children: [
              // Messages
              Expanded(
                child: chat.messages.isEmpty
                    ? const Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.auto_awesome, size: 48,
                                color: Color(0xFF3B82F6)),
                            SizedBox(height: 16),
                            Text('AI Agent',
                                style: TextStyle(
                                    fontSize: 24, color: Color(0xFF888888))),
                            SizedBox(height: 8),
                            Text('Ask anything, create content',
                                style: TextStyle(
                                    fontSize: 14, color: Color(0xFF666666))),
                          ],
                        ),
                      )
                    : ListView.builder(
                        controller: _scrollController,
                        padding: const EdgeInsets.all(16),
                        itemCount: chat.messages.length,
                        itemBuilder: (context, i) {
                          final msg = chat.messages[i];
                          return _MessageBubble(message: msg);
                        },
                      ),
              ),

              // Tool indicator
              if (chat.currentTool.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                  child: Row(
                    children: [
                      const SizedBox(
                        width: 14, height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        'Using ${chat.currentTool}...',
                        style: const TextStyle(
                            fontSize: 12, color: Color(0xFF888888)),
                      ),
                    ],
                  ),
                ),

              // Input
              Container(
                padding: const EdgeInsets.all(12),
                decoration: const BoxDecoration(
                  border: Border(
                    top: BorderSide(color: Color(0xFF262626)),
                  ),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _controller,
                        maxLines: 4,
                        minLines: 1,
                        textInputAction: TextInputAction.send,
                        onSubmitted: (_) => _send(chat),
                        decoration: const InputDecoration(
                          hintText: 'Type your message...',
                          hintStyle: TextStyle(color: Color(0xFF666666)),
                          contentPadding: EdgeInsets.symmetric(
                              horizontal: 16, vertical: 12),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Container(
                      decoration: BoxDecoration(
                        color: const Color(0xFF3B82F6),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: IconButton(
                        icon: chat.isLoading
                            ? const SizedBox(
                                width: 20, height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2, color: Colors.white))
                            : const Icon(Icons.send, color: Colors.white),
                        onPressed: chat.isLoading ? null : () => _send(chat),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  void _send(ChatProvider chat) {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    _controller.clear();
    chat.sendMessage(text);
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }
}

class _MessageBubble extends StatelessWidget {
  final ChatMessage message;

  const _MessageBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == 'user';

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.78,
        ),
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: isUser ? const Color(0xFF3B82F6) : const Color(0xFF141414),
          borderRadius: BorderRadius.circular(18),
          border: isUser
              ? null
              : Border.all(color: const Color(0xFF262626)),
        ),
        child: isUser
            ? Text(message.content,
                style: const TextStyle(color: Colors.white, height: 1.5))
            : MarkdownBody(
                data: message.content.isEmpty ? '...' : message.content,
                styleSheet: MarkdownStyleSheet(
                  p: const TextStyle(color: Color(0xFFEDEDED), height: 1.6),
                  code: const TextStyle(
                    backgroundColor: Color(0xFF1E1E1E),
                    color: Color(0xFFE0E0E0),
                    fontSize: 13,
                  ),
                  codeblockDecoration: BoxDecoration(
                    color: const Color(0xFF1E1E1E),
                    borderRadius: BorderRadius.circular(8),
                  ),
                ),
              ),
      ),
    );
  }
}
