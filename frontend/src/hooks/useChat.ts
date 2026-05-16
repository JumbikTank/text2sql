import { useRef } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useChatStore } from '@/store/chatStore';
import { apiClient } from '@/services/api';
import type { Message } from '@/types/message';

function isAbort(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const e = error as { name?: string; code?: string; message?: string };
  return e.name === 'CanceledError' || e.code === 'ERR_CANCELED' || e.message === 'canceled';
}

export const useChat = () => {
  const { messages, addMessage, updateMessage, setLoading, setError, clearError } = useChatStore();
  const sendAbortRef = useRef<AbortController | null>(null);
  const replayAbortRef = useRef<AbortController | null>(null);

  const sendMessageMutation = useMutation({
    mutationFn: async (content: string) => {
      const userMessage: Message = {
        role: 'user',
        content,
        type: 'plain',
      };

      addMessage(userMessage);
      clearError();

      const controller = new AbortController();
      sendAbortRef.current = controller;
      try {
        return await apiClient.sendMessages([...messages, userMessage], controller.signal);
      } finally {
        sendAbortRef.current = null;
      }
    },
    onMutate: () => {
      setLoading(true);
    },
    onSuccess: (response) => {
      addMessage(response);
      setLoading(false);
    },
    onError: (error: any) => {
      setLoading(false);
      if (isAbort(error)) return;
      setError(error.error || error.message || 'An error occurred while sending your message');
    },
  });

  const sendMessage = (content: string) => {
    sendMessageMutation.mutate(content);
  };

  const cancelSend = () => {
    sendAbortRef.current?.abort();
    replayAbortRef.current?.abort();
  };

  const replayQueryMutation = useMutation({
    mutationFn: async ({ messageId, sqlQuery }: { messageId: string; sqlQuery: string }) => {
      const controller = new AbortController();
      replayAbortRef.current = controller;
      try {
        const response = await apiClient.executeSql(sqlQuery, controller.signal);
        return { response, messageId };
      } finally {
        replayAbortRef.current = null;
      }
    },
    onMutate: () => {
      setLoading(true);
      clearError();
    },
    onSuccess: ({ response, messageId }) => {
      updateMessage(messageId, {
        content: response.content,
        download_link: response.download_link,
        preview_data: response.preview_data,
        lastUpdated: new Date(),
      });
      setLoading(false);
    },
    onError: (error: any) => {
      setLoading(false);
      if (isAbort(error)) return;
      setError(error.error || error.message || 'An error occurred while replaying the query');
    },
  });

  const replayQuery = (messageId: string, sqlQuery: string) => {
    replayQueryMutation.mutate({ messageId, sqlQuery });
  };

  return {
    messages,
    sendMessage,
    cancelSend,
    replayQuery,
    isLoading: sendMessageMutation.isPending || replayQueryMutation.isPending,
  };
};
