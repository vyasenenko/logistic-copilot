"use client";

import { useEffect, useState } from "react";
import { MessageSquare, Plus } from "lucide-react";
import { PUBLIC_API_URL as API_URL } from "@/constants/publicApi";

function authHeaders(): HeadersInit {
  const authToken =
    typeof window !== "undefined"
      ? window.localStorage.getItem("logistic_copilot_auth_token")
      : null;
  return authToken ? { Authorization: `Bearer ${authToken}` } : {};
}

interface Conversation {
  id: string;
  title: string;
  created_at: string;
  message_count: number;
}

interface SidebarProps {
  currentConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
}

export function Sidebar({
  currentConversationId,
  onSelectConversation,
  onNewConversation,
}: SidebarProps) {
  const [conversations, setConversations] = useState<Conversation[]>([]);

  useEffect(() => {
    fetch(`${API_URL}/api/conversations`, { headers: authHeaders() })
      .then((r) => r.json())
      .then(setConversations)
      .catch(() => {});
  }, [currentConversationId]);

  return (
    <aside className="w-64 h-full bg-agent-surface border-r border-agent-border flex flex-col">
      <div className="p-3">
        <button
          onClick={onNewConversation}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg border border-agent-border hover:bg-agent-bg transition text-sm"
        >
          <Plus size={16} />
          New chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
        {conversations.map((conv) => (
          <button
            key={conv.id}
            onClick={() => onSelectConversation(conv.id)}
            className={`w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm truncate transition ${
              conv.id === currentConversationId
                ? "bg-agent-bg text-agent-text"
                : "text-agent-muted hover:text-agent-text hover:bg-agent-bg"
            }`}
          >
            <MessageSquare size={14} className="shrink-0" />
            <span className="truncate">{conv.title}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}
