"use client";

import { Chat } from "@/components/Chat";
import { Sidebar } from "@/components/Sidebar";
import { useState } from "react";

export default function Home() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="flex h-screen">
      {sidebarOpen && (
        <Sidebar
          currentConversationId={conversationId}
          onSelectConversation={setConversationId}
          onNewConversation={() => setConversationId(null)}
        />
      )}
      <main className="flex-1 flex flex-col">
        <header className="h-12 flex items-center px-4 border-b border-agent-border">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="text-agent-muted hover:text-agent-text mr-4"
          >
            ☰
          </button>
          <h1 className="text-sm font-medium text-agent-muted">AI Agent</h1>
        </header>
        <Chat
          conversationId={conversationId}
          onConversationCreated={setConversationId}
        />
      </main>
    </div>
  );
}
