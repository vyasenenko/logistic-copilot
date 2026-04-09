"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Send, Loader2, Wrench } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface ToolEvent {
  tool: string;
  status: "running" | "done";
}

interface ChatProps {
  conversationId: string | null;
  onConversationCreated: (id: string) => void;
}

export function Chat({ conversationId, onConversationCreated }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [activeTools, setActiveTools] = useState<ToolEvent[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Load messages when conversation changes
  useEffect(() => {
    if (!conversationId) {
      setMessages([]);
      return;
    }
    fetch(`${API_URL}/api/conversations/${conversationId}/messages`)
      .then((r) => r.json())
      .then((data) =>
        setMessages(
          data.map((m: { role: string; content: string }) => ({
            role: m.role as "user" | "assistant",
            content: m.content,
          }))
        )
      )
      .catch(() => {});
  }, [conversationId]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, activeTools]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    setInput("");
    setIsLoading(true);
    setActiveTools([]);

    // Add user message
    setMessages((prev) => [...prev, { role: "user", content: text }]);

    try {
      const response = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: text,
          conversation_id: conversationId,
        }),
      });

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let assistantContent = "";

      // Add empty assistant message
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;

          try {
            const event = JSON.parse(line.slice(6));

            if (event.event === "token") {
              assistantContent += event.data;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  role: "assistant",
                  content: assistantContent,
                };
                return updated;
              });
            } else if (event.event === "tool_start") {
              setActiveTools((prev) => [
                ...prev,
                { tool: event.data, status: "running" },
              ]);
            } else if (event.event === "tool_end") {
              setActiveTools((prev) =>
                prev.map((t) =>
                  t.status === "running" ? { ...t, status: "done" } : t
                )
              );
            }

            // Capture conversation ID
            if (event.conversation_id && !conversationId) {
              onConversationCreated(event.conversation_id);
            }
          } catch {
            // skip malformed lines
          }
        }
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Connection error. Please check the backend is running.",
        },
      ]);
    }

    setIsLoading(false);
    setActiveTools([]);
  };

  return (
    <div className="flex-1 flex flex-col">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-agent-muted">
              <p className="text-2xl mb-2">AI Agent</p>
              <p className="text-sm">Ask me anything. I can search, calculate, remember.</p>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[75%] rounded-2xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-agent-accent text-white"
                  : "bg-agent-surface border border-agent-border"
              }`}
            >
              {msg.role === "assistant" ? (
                <div className="markdown-content">
                  <ReactMarkdown>{msg.content || "..."}</ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}
            </div>
          </div>
        ))}

        {/* Active tools indicator */}
        {activeTools.length > 0 && (
          <div className="flex items-center gap-2 text-agent-muted text-sm">
            <Wrench size={14} className="animate-spin" />
            {activeTools
              .filter((t) => t.status === "running")
              .map((t) => t.tool)
              .join(", ")}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-agent-border">
        <div className="flex items-center gap-2 bg-agent-surface border border-agent-border rounded-2xl px-4 py-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder="Type your message..."
            rows={1}
            className="flex-1 bg-transparent outline-none resize-none text-agent-text placeholder-agent-muted"
          />
          <button
            onClick={sendMessage}
            disabled={isLoading || !input.trim()}
            className="p-2 rounded-xl bg-agent-accent hover:bg-agent-accent-hover disabled:opacity-50 transition-colors"
          >
            {isLoading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
      </div>
    </div>
  );
}
