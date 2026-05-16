import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Message } from '@/types/message';

interface ChatState {
  messages: Message[];
  isLoading: boolean;
  error: string | null;

  // Actions
  addMessage: (message: Message) => void;
  addMessages: (messages: Message[]) => void;
  updateMessage: (id: string, updates: Partial<Message>) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearMessages: () => void;
  clearError: () => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      messages: [],
      isLoading: false,
      error: null,

      addMessage: (message) =>
        set((state) => ({
          messages: [...state.messages, { ...message, id: crypto.randomUUID(), timestamp: new Date() }],
        })),

      addMessages: (messages) =>
        set((state) => ({
          messages: [
            ...state.messages,
            ...messages.map((msg) => ({
              ...msg,
              id: msg.id || crypto.randomUUID(),
              timestamp: msg.timestamp || new Date(),
            })),
          ],
        })),

      updateMessage: (id, updates) =>
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === id ? { ...msg, ...updates } : msg
          ),
        })),

      setLoading: (loading) => set({ isLoading: loading }),

      setError: (error) => set({ error }),

      clearMessages: () => set({ messages: [], error: null }),

      clearError: () => set({ error: null }),
    }),
    {
      name: 'chat-storage',
      partialize: (state) => ({ messages: state.messages }),
    }
  )
);
