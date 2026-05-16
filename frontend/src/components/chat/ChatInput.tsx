import { useState, KeyboardEvent, useRef, useEffect } from 'react';
import { Send } from 'lucide-react';
import { Button } from '../ui/Button';
import { Textarea } from '../ui/Textarea';
import { cn } from '@/utils/cn';

interface ChatInputProps {
  onSend: (message: string) => void;
  onCancel?: () => void;
  isLoading: boolean;
  disabled?: boolean;
}

const MAX_INPUT_LENGTH = 2000;

export const ChatInput: React.FC<ChatInputProps> = ({ onSend, onCancel, isLoading, disabled }) => {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [input]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading || disabled) return;
    if (trimmed.length > MAX_INPUT_LENGTH) return;

    onSend(trimmed);
    setInput('');

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const atLimit = input.length >= MAX_INPUT_LENGTH;

  return (
    <div className="border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
      <div className="max-w-4xl mx-auto">
        <div className="flex gap-3 items-end">
          <div className="flex-1 relative">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value.slice(0, MAX_INPUT_LENGTH))}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question about your data..."
              disabled={disabled || isLoading}
              maxLength={MAX_INPUT_LENGTH}
              rows={1}
              className={cn(
                'min-h-[52px] max-h-[200px] pr-12',
                'bg-gray-50 dark:bg-gray-800/50',
                'border-2 border-gray-200 dark:border-gray-700',
                'focus:border-purple-500 dark:focus:border-purple-500'
              )}
            />
            <div className="absolute right-2 bottom-2 text-xs text-gray-400">
              {input.length > 0 && (
                <span className={cn('mr-2', atLimit && 'text-red-500 font-medium')}>
                  {input.length} / {MAX_INPUT_LENGTH}
                </span>
              )}
              <kbd className="px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                ⏎
              </kbd>
            </div>
          </div>

          {isLoading && onCancel ? (
            <Button
              onClick={onCancel}
              variant="secondary"
              size="lg"
              className="px-6"
              title="Stop the current request"
            >
              Stop
            </Button>
          ) : (
            <Button
              onClick={handleSend}
              disabled={!input.trim() || isLoading || disabled}
              isLoading={isLoading}
              size="lg"
              className="px-6"
            >
              {!isLoading && <Send className="w-5 h-5" />}
            </Button>
          )}
        </div>

        <p className="mt-2 text-xs text-gray-500 dark:text-gray-400 text-center">
          Press <kbd className="px-1 py-0.5 rounded bg-gray-200 dark:bg-gray-700">Enter</kbd> to send,{' '}
          <kbd className="px-1 py-0.5 rounded bg-gray-200 dark:bg-gray-700">Shift + Enter</kbd> for new line
        </p>
      </div>
    </div>
  );
};
