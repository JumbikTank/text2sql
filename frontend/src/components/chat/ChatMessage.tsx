import { useState, forwardRef } from 'react';
import { motion } from 'framer-motion';
import { Download, User, Bot, RotateCcw, ExternalLink, Table2, List } from 'lucide-react';
import { format } from 'date-fns';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '@/types/message';
import { MessageContent } from './MessageContent';
import { CodeBlock } from './CodeBlock';
import { Button } from '../ui/Button';
import { apiClient } from '@/services/api';
import { downloadBlob, getFilenameFromUrl } from '@/utils/download';
import { parseCsv } from '@/utils/csv';
import { cn } from '@/utils/cn';
import { useChatStore } from '@/store/chatStore';
import { useNotificationStore } from '@/store/notificationStore';

const RESULTS_WINDOW_SHELL = `<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Query Results</title>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
        font-size: 13px; padding: 20px; background: #fafafa;
      }
      .container { background: white; padding: 20px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
      h1 { font-size: 18px; color: #333; margin-bottom: 8px; padding-bottom: 10px; border-bottom: 2px solid #e0e0e0; }
      #timestamp { font-size: 11px; color: #666; margin-bottom: 15px; }
      h2 { font-size: 14px; color: #555; margin-top: 20px; margin-bottom: 8px; }
      pre {
        background: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto;
        font-size: 11px; line-height: 1.5; border: 1px solid #e0e0e0;
        white-space: pre; font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
      }
      .table-wrapper { overflow-x: auto; margin-top: 10px; }
      table { border-collapse: collapse; width: 100%; font-size: 12px; min-width: 600px; }
      th, td { border: 1px solid #e0e0e0; padding: 6px 10px; text-align: left; }
      th { background: #f8f8f8; font-weight: 600; position: sticky; top: 0; z-index: 10; }
      tr:nth-child(even) { background: #fafafa; }
      tr:hover { background: #f0f0f0; }
      #print-btn {
        position: fixed; top: 20px; right: 20px; padding: 8px 16px;
        background: #4CAF50; color: white; border: none; border-radius: 4px;
        cursor: pointer; font-size: 12px;
      }
      #print-btn:hover { background: #45a049; }
      @media print { #print-btn { display: none; } body { padding: 0; background: white; } }
    </style>
  </head>
  <body>
    <button id="print-btn">Print</button>
    <div class="container">
      <h1>Query Results</h1>
      <div id="timestamp"></div>
      <h2>SQL Query:</h2>
      <pre id="sql"></pre>
      <h2 id="row-count"></h2>
      <div class="table-wrapper">
        <table>
          <thead id="thead"></thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>
    </div>
  </body>
</html>`;

interface ChatMessageProps {
  message: Message;
  onReplay?: (content: string) => void;
}

export const ChatMessage = forwardRef<HTMLDivElement, ChatMessageProps>(({ message, onReplay }, ref) => {
  const isUser = message.role === 'user';
  const [tableOrientation, setTableOrientation] = useState<'horizontal' | 'vertical'>('horizontal');
  const [isReplaying, setIsReplaying] = useState(false);
  const { updateMessage } = useChatStore();
  const { addNotification, dismissNotification } = useNotificationStore();

  const handleDownload = async () => {
    if (!message.download_link) return;

    try {
      const blob = await apiClient.downloadCsv(message.download_link);
      const filename = getFilenameFromUrl(message.download_link);
      downloadBlob(blob, filename);
    } catch (error) {
      console.error('Failed to download file:', error);
    }
  };

  const handleReplay = async () => {
    if (!message.sql_query || !message.id) return;

    setIsReplaying(true);

    // Show "in progress" notification
    const inProgressId = addNotification({
      type: 'info',
      title: 'Executing Query',
      message: 'Running SQL query against the database...',
      autoDismiss: false,
    });

    const startTime = Date.now();

    try {
      // Re-execute the SQL query directly (faster, no LLM regeneration)
      const response = await apiClient.executeSql(message.sql_query);

      // Update the current assistant message with new results
      updateMessage(message.id, {
        content: response.content,
        preview_data: response.preview_data,
        download_link: response.download_link,
        type: response.type,
        lastUpdated: new Date(),
      });

      // Dismiss the in-progress notification
      dismissNotification(inProgressId);

      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      addNotification({
        type: 'success',
        title: 'Query Replayed',
        message: `Query executed successfully in ${elapsed}s. Results have been updated.`,
      });
    } catch (error) {
      // Dismiss the in-progress notification
      dismissNotification(inProgressId);

      console.error('Failed to replay query:', error);
      const apiError = error as { error?: string; detail?: string };
      const errorMessage = apiError.detail || apiError.error || 'Unknown error occurred';
      addNotification({
        type: 'error',
        title: 'Query Failed',
        message: errorMessage,
        autoDismiss: false,
      });
    } finally {
      setIsReplaying(false);
    }
  };

  const handleOpenInNewTab = async () => {
    if (!message.download_link || !message.sql_query) return;

    try {
      const blob = await apiClient.downloadCsv(message.download_link);
      const text = await blob.text();
      const rows = parseCsv(text);
      const headers = rows[0] ?? [];
      const dataRows = rows.slice(1).filter((r) => r.some((c) => c !== ''));

      const timestamp = message.timestamp
        ? new Date(message.timestamp).toLocaleString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
          })
        : 'N/A';

      const newWindow = window.open('', '_blank', 'width=1200,height=800');
      if (!newWindow) return;

      // Write a static HTML shell, then inject user content via DOM APIs so
      // CSV values and SQL never get interpreted as markup.
      newWindow.document.write(RESULTS_WINDOW_SHELL);
      newWindow.document.close();

      const doc = newWindow.document;
      doc.title = 'Query Results';

      const tsEl = doc.getElementById('timestamp');
      if (tsEl) tsEl.textContent = `Generated: ${timestamp}`;

      const sqlEl = doc.getElementById('sql');
      if (sqlEl) sqlEl.textContent = message.sql_query;

      const countEl = doc.getElementById('row-count');
      if (countEl) countEl.textContent = `Results (${dataRows.length} rows):`;

      const thead = doc.getElementById('thead');
      const tbody = doc.getElementById('tbody');
      if (thead && tbody) {
        const headRow = doc.createElement('tr');
        headers.forEach((h) => {
          const th = doc.createElement('th');
          th.textContent = h;
          headRow.appendChild(th);
        });
        thead.appendChild(headRow);

        dataRows.forEach((cells) => {
          const tr = doc.createElement('tr');
          cells.forEach((cell) => {
            const td = doc.createElement('td');
            td.textContent = cell;
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
      }

      const printBtn = doc.getElementById('print-btn');
      if (printBtn) printBtn.addEventListener('click', () => newWindow.print());
    } catch (error) {
      console.error('Failed to open results in new tab:', error);
      addNotification({
        type: 'error',
        title: 'Could not open results',
        message: 'Failed to load full results. Try downloading the CSV instead.',
      });
    }
  };

  // Helper function to convert horizontal markdown table to vertical format
  const convertToVerticalFormat = (markdown: string): string => {
    const lines = markdown.trim().split('\n');
    if (lines.length < 3) return markdown;

    // Parse header row
    const headers = lines[0].split('|').filter(cell => cell.trim()).map(h => h.trim());

    // Parse data rows (skip separator line at index 1)
    const dataRows: string[][] = [];
    for (let i = 2; i < lines.length; i++) {
      const cells = lines[i].split('|').filter(cell => cell.trim()).map(c => c.trim());
      if (cells.length > 0) {
        dataRows.push(cells);
      }
    }

    // Convert to vertical format (Field | Value pairs for each row)
    let verticalMarkdown = '';
    dataRows.forEach((row, rowIndex) => {
      if (rowIndex > 0) verticalMarkdown += '\n---\n\n';
      verticalMarkdown += `**Row ${rowIndex + 1}:**\n\n`;
      verticalMarkdown += '| Field | Value |\n';
      verticalMarkdown += '|-------|-------|\n';
      headers.forEach((header, colIndex) => {
        const value = row[colIndex] || '';
        verticalMarkdown += `| ${header} | ${value} |\n`;
      });
    });

    return verticalMarkdown;
  };

  // Get the preview data in the selected orientation
  const getFormattedPreview = (): string => {
    if (!message.preview_data) return '';
    if (tableOrientation === 'horizontal') {
      return message.preview_data;
    }
    return convertToVerticalFormat(message.preview_data);
  };

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={cn(
        'flex gap-4 p-6',
        isUser ? 'bg-transparent' : 'bg-gradient-to-r from-purple-50/50 via-transparent to-blue-50/50 dark:from-gray-800/50 dark:via-transparent dark:to-gray-800/50'
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          'flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center shadow-lg',
          isUser
            ? 'bg-gradient-to-br from-purple-600 to-blue-600'
            : 'bg-gradient-to-br from-green-500 to-teal-500'
        )}
      >
        {isUser ? <User className="w-5 h-5 text-white" /> : <Bot className="w-5 h-5 text-white" />}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3 mb-2">
          <span className="font-semibold text-gray-900 dark:text-gray-100">
            {isUser ? 'You' : 'Assistant'}
          </span>
          {message.lastUpdated ? (
            <span className="text-xs text-gray-500 dark:text-gray-400" title={format(new Date(message.lastUpdated), 'PPpp')}>
              Last updated: {format(new Date(message.lastUpdated), 'MMM d, h:mm:ss a')}
            </span>
          ) : message.timestamp ? (
            <span className="text-xs text-gray-500 dark:text-gray-400" title={format(new Date(message.timestamp), 'PPpp')}>
              {format(new Date(message.timestamp), 'MMM d, h:mm:ss a')}
            </span>
          ) : null}
        </div>

        {/* Only show content if it's not a data message with preview, or if content is not a table */}
        {message.content && (!message.preview_data || !message.content.includes('|')) && (
          <div className="text-gray-800 dark:text-gray-200">
            <MessageContent content={message.content} type={message.type} />
          </div>
        )}

        {/* SQL Query section with copy button */}
        {message.sql_query && (
          <div className="mt-4">
            <CodeBlock code={message.sql_query} language="sql" />
          </div>
        )}

        {/* Preview Data section with orientation toggle */}
        {message.preview_data && (
          <div className="mt-4">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Preview (first 10 rows):</h4>
              <div className="flex gap-1">
                <Button
                  onClick={() => setTableOrientation('horizontal')}
                  variant={tableOrientation === 'horizontal' ? 'primary' : 'secondary'}
                  size="sm"
                  className="gap-1 py-1 px-2"
                  title="Horizontal table view"
                >
                  <Table2 className="w-3 h-3" />
                </Button>
                <Button
                  onClick={() => setTableOrientation('vertical')}
                  variant={tableOrientation === 'vertical' ? 'primary' : 'secondary'}
                  size="sm"
                  className="gap-1 py-1 px-2"
                  title="Vertical card view"
                >
                  <List className="w-3 h-3" />
                </Button>
              </div>
            </div>
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  table({ children }) {
                    return (
                      <div className="overflow-x-auto my-2">
                        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                          {children}
                        </table>
                      </div>
                    );
                  },
                  thead({ children }) {
                    return <thead className="bg-gray-50 dark:bg-gray-800">{children}</thead>;
                  },
                  th({ children }) {
                    return (
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                        {children}
                      </th>
                    );
                  },
                  td({ children }) {
                    return (
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
                        {children}
                      </td>
                    );
                  },
                }}
              >
                {getFormattedPreview()}
              </ReactMarkdown>
            </div>
          </div>
        )}

        {/* Action buttons for data messages */}
        {message.download_link && (
          <div className="mt-4 flex gap-2">
            <Button
              onClick={handleDownload}
              variant="secondary"
              size="sm"
              className="gap-2"
            >
              <Download className="w-4 h-4" />
              Download CSV
            </Button>
            {message.preview_data && (
              <Button
                onClick={handleOpenInNewTab}
                variant="secondary"
                size="sm"
                className="gap-2"
              >
                <ExternalLink className="w-4 h-4" />
                Open in New Tab
              </Button>
            )}
          </div>
        )}

        {/* Replay button for assistant messages with SQL query */}
        {!isUser && message.sql_query && (
          <div className="mt-4">
            <Button
              onClick={handleReplay}
              variant="secondary"
              size="sm"
              className="gap-2"
              disabled={isReplaying}
            >
              <RotateCcw className={cn("w-4 h-4", isReplaying && "animate-spin")} />
              {isReplaying ? 'Replaying...' : 'Replay Query'}
            </Button>
          </div>
        )}

        {/* Ask-again button for user messages: re-runs the full LLM pipeline. */}
        {isUser && onReplay && (
          <div className="mt-4">
            <Button
              onClick={() => onReplay(message.content)}
              variant="secondary"
              size="sm"
              className="gap-2"
            >
              <RotateCcw className="w-4 h-4" />
              Ask Again
            </Button>
          </div>
        )}
      </div>
    </motion.div>
  );
});

ChatMessage.displayName = 'ChatMessage';
