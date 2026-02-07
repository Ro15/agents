import { useEffect, useState } from "react";
import type { ChatResponse } from "../types";

export type ChatMessage =
  | { role: "user"; content: string; createdAt: string }
  | { role: "assistant"; content: ChatResponse; createdAt: string };

export function useLocalChats(plugin: string, datasetId: string | null) {
  const key = `chat-${plugin}-${datasetId || "none"}`;
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : [];
  });

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(messages));
  }, [messages, key]);

  useEffect(() => {
    const raw = localStorage.getItem(key);
    setMessages(raw ? JSON.parse(raw) : []);
  }, [key]);

  return { messages, setMessages };
}
