import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Loader2, AlertCircle } from 'lucide-react';
import { ChatMessage } from './ChatMessage';
import { useChatStore } from '@/store/chatStore';
import { useChat } from '@/hooks/useChat';
import { cn } from '@/utils/cn';

export const ChatContainer: React.FC = () => {
  const { messages, isLoading, error } = useChatStore();
  const { sendMessage } = useChat();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const hasMessages = messages.length > 0;

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto scroll-smooth"
    >
      <div className="max-w-4xl mx-auto px-4">
      {!hasMessages && !isLoading && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="h-full flex items-center justify-center p-8"
        >
          <div className="text-center max-w-2xl">
            <div className="mb-6 relative">
              <div className="w-20 h-20 mx-auto rounded-full bg-gradient-to-br from-purple-600 to-blue-600 flex items-center justify-center shadow-2xl">
                <svg
                  className="w-10 h-10 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                  />
                </svg>
              </div>
              <div className="absolute inset-0 bg-gradient-to-r from-purple-600/20 to-blue-600/20 blur-3xl -z-10" />
            </div>

            <h2 className="text-3xl font-bold mb-3 bg-gradient-to-r from-purple-600 to-blue-600 bg-clip-text text-transparent">
              Welcome to Text2SQL
            </h2>
            <p className="text-lg text-gray-600 dark:text-gray-400 mb-6">
              Ask questions about your data in natural language
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-8">
              {[
                { title: 'Natural Language', desc: 'Ask questions in plain English or Russian' },
                { title: 'SQL Generation', desc: 'Automatic SQL query generation' },
                { title: 'Data Export', desc: 'Download results as CSV files' },
                { title: 'Smart Context', desc: 'Follow-up questions with context' },
              ].map((feature, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.1 }}
                  className={cn(
                    'p-4 rounded-lg',
                    'bg-gradient-to-br from-gray-50 to-gray-100',
                    'dark:from-gray-800 dark:to-gray-900',
                    'border border-gray-200 dark:border-gray-700'
                  )}
                >
                  <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-1">
                    {feature.title}
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400">{feature.desc}</p>
                </motion.div>
              ))}
            </div>
          </div>
        </motion.div>
      )}

      <AnimatePresence mode="popLayout">
        {messages.map((message) => (
          <ChatMessage
            key={message.id}
            message={message}
            onReplay={sendMessage}
          />
        ))}
      </AnimatePresence>

      {isLoading && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="flex gap-4 p-6 bg-gradient-to-r from-purple-50/50 via-transparent to-blue-50/50 dark:from-gray-800/50 dark:via-transparent dark:to-gray-800/50"
        >
          <div className="flex-shrink-0 w-10 h-10 rounded-full bg-gradient-to-br from-green-500 to-teal-500 flex items-center justify-center shadow-lg">
            <Loader2 className="w-5 h-5 text-white animate-spin" />
          </div>
          <div className="flex-1">
            <span className="font-semibold text-gray-900 dark:text-gray-100">Assistant</span>
            <div className="mt-2 flex items-center gap-2 text-gray-600 dark:text-gray-400">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-purple-600 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-purple-600 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-purple-600 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
              <span className="text-sm">Thinking...</span>
            </div>
          </div>
        </motion.div>
      )}

      {error && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mx-6 my-4 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800"
        >
          <div className="flex gap-3">
            <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <h4 className="font-semibold text-red-900 dark:text-red-100 mb-1">Error</h4>
              <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
            </div>
          </div>
        </motion.div>
      )}

      <div ref={messagesEndRef} />
      </div>
    </div>
  );
};
