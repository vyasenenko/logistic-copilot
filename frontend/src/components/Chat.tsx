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
  toolInput?: Record<string, unknown>;
  toolOutput?: string;
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
              const raw = event.data;
              const toolName =
                typeof raw === "string"
                  ? raw
                  : String(raw?.tool_name || raw?.name || "tool");
              const toolInput =
                typeof raw === "object" && raw !== null && "tool_input" in raw
                  ? (raw.tool_input as Record<string, unknown>)
                  : undefined;
              setActiveTools((prev) => [
                ...prev,
                { tool: toolName, status: "running", toolInput },
              ]);
            } else if (event.event === "tool_end") {
              const raw = event.data;
              const toolName =
                typeof raw === "object" && raw !== null && "tool_name" in raw
                  ? String((raw as { tool_name: string }).tool_name)
                  : null;
              const toolOutput =
                typeof raw === "object" && raw !== null && "tool_output" in raw
                  ? String((raw as { tool_output: string }).tool_output)
                  : typeof raw === "string"
                    ? raw
                    : undefined;
              setActiveTools((prev) => {
                if (prev.length === 0) return prev;
                if (toolName) {
                  let matched = false;
                  return prev.map((t) => {
                    if (!matched && t.status === "running" && t.tool === toolName) {
                      matched = true;
                      return {
                        ...t,
                        status: "done" as const,
                        toolOutput: toolOutput ?? t.toolOutput,
                      };
                    }
                    return t;
                  });
                }
                let seen = false;
                return prev.map((t) => {
                  if (!seen && t.status === "running") {
                    seen = true;
                    return {
                      ...t,
                      status: "done" as const,
                      toolOutput: toolOutput ?? t.toolOutput,
                    };
                  }
                  return t;
                });
              });
            } else if (event.event === "error") {
              const errText =
                typeof event.data === "string" ? event.data : JSON.stringify(event.data);
              assistantContent += `\n\n[Error] ${errText}`;
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  role: "assistant",
                  content: assistantContent,
                };
                return updated;
              });
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
          <div className="flex flex-col gap-1 text-agent-muted text-sm border border-agent-border rounded-xl p-3 bg-agent-surface/50">
            <div className="flex items-center gap-2">
              <Wrench size={14} className="animate-spin shrink-0" />
              <span>Tools</span>
            </div>
            <ul className="space-y-1 font-mono text-xs break-all">
              {activeTools.map((t, idx) => (
                <li key={`${t.tool}-${idx}`}>
                  <span className="text-agent-text">{t.tool}</span>{" "}
                  <span className="opacity-70">({t.status})</span>
                  {t.toolInput && Object.keys(t.toolInput).length > 0 && (
                    <pre className="mt-1 whitespace-pre-wrap text-[11px] opacity-80 max-h-24 overflow-y-auto">
                      {JSON.stringify(t.toolInput, null, 0)}
                    </pre>
                  )}
                  {t.toolOutput && t.status === "done" && (
                    <pre className="mt-1 whitespace-pre-wrap text-[11px] opacity-70 max-h-20 overflow-y-auto">
                      {t.toolOutput.slice(0, 800)}
                      {t.toolOutput.length > 800 ? "…" : ""}
                    </pre>
                  )}
                </li>
              ))}
            </ul>
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
