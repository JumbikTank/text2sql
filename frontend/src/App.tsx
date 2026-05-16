import { useState, useEffect, useCallback, useRef } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Trash2, PanelLeftClose, PanelLeft, Eye, Wifi, WifiOff, GripVertical } from 'lucide-react';
import { ChatContainer } from './components/chat/ChatContainer';
import { ChatInput } from './components/chat/ChatInput';
import { Button } from './components/ui/Button';
import { Modal } from './components/ui/Modal';
import { ToastContainer } from './components/ui/ToastContainer';
import { useChat } from './hooks/useChat';
import { useWebSocket } from './hooks/useWebSocket';
import { useChatStore } from './store/chatStore';
import { useSchemaStore } from './store/schemaStore';
import { useConnectionStore } from './store/connectionStore';
import { useConnections } from './hooks/useConnection';
import { useSchema } from './hooks/useSchema';
import { ErrorBoundary } from './components/ErrorBoundary';
import { ConnectionStatus } from './components/connection/ConnectionStatus';
import { ConnectionForm } from './components/connection/ConnectionForm';
import { ConnectionList } from './components/connection/ConnectionList';
import { TableBrowser } from './components/schema/TableBrowser';
import { TableDetails } from './components/schema/TableDetails';
import { TablePreview } from './components/schema/TablePreview';
import type { DatabaseConnectionConfig } from './types/schema';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function ConnectionModal() {
  const { isModalOpen, editingConnection, closeModal } = useConnectionStore();

  return (
    <Modal
      isOpen={isModalOpen}
      onClose={closeModal}
      title={editingConnection ? 'Edit Connection' : 'New Connection'}
      size="lg"
    >
      <ConnectionForm
        initialData={editingConnection}
        onSuccess={closeModal}
        onCancel={closeModal}
      />
    </Modal>
  );
}

function ConnectionSettingsModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const { openModal } = useConnectionStore();

  const handleEdit = (connection: DatabaseConnectionConfig) => {
    openModal(connection);
  };

  const handleAddNew = () => {
    openModal();
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Database Connections" size="lg">
      <ConnectionList onEdit={handleEdit} onAddNew={handleAddNew} />
    </Modal>
  );
}

const MIN_SIDEBAR_WIDTH = 200;
const MAX_SIDEBAR_WIDTH = 600;
const DEFAULT_SIDEBAR_WIDTH = 288; // 72 * 4 = 288px (w-72)

function Sidebar() {
  const { isSidebarOpen, toggleSidebar, selectedTable, previewData } = useSchemaStore();
  const { previewTable, isLoadingPreview } = useSchema();
  const [showPreview, setShowPreview] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = localStorage.getItem('sidebarWidth');
    return saved ? parseInt(saved, 10) : DEFAULT_SIDEBAR_WIDTH;
  });
  const [isResizing, setIsResizing] = useState(false);
  const sidebarRef = useRef<HTMLDivElement>(null);

  const handlePreview = async (tableName: string) => {
    await previewTable(tableName);
    setShowPreview(true);
  };

  const startResizing = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  }, []);

  const stopResizing = useCallback(() => {
    setIsResizing(false);
  }, []);

  const resize = useCallback(
    (e: MouseEvent) => {
      if (!isResizing || !sidebarRef.current) return;

      const newWidth = e.clientX - sidebarRef.current.getBoundingClientRect().left;
      const clampedWidth = Math.min(Math.max(newWidth, MIN_SIDEBAR_WIDTH), MAX_SIDEBAR_WIDTH);
      setSidebarWidth(clampedWidth);
      localStorage.setItem('sidebarWidth', String(clampedWidth));
    },
    [isResizing]
  );

  useEffect(() => {
    if (isResizing) {
      window.addEventListener('mousemove', resize);
      window.addEventListener('mouseup', stopResizing);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    }

    return () => {
      window.removeEventListener('mousemove', resize);
      window.removeEventListener('mouseup', stopResizing);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [isResizing, resize, stopResizing]);

  if (!isSidebarOpen) {
    return (
      <div className="flex flex-col border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <button
          onClick={toggleSidebar}
          className="p-3 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          title="Open sidebar"
        >
          <PanelLeft className="w-5 h-5 text-gray-500" />
        </button>
      </div>
    );
  }

  return (
    <div
      ref={sidebarRef}
      className="relative flex flex-col border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900"
      style={{ width: sidebarWidth }}
    >
      {/* Sidebar Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100">Tables</h2>
        <button
          onClick={toggleSidebar}
          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          title="Close sidebar"
        >
          <PanelLeftClose className="w-5 h-5 text-gray-500" />
        </button>
      </div>

      {/* Table Browser */}
      <div className="flex-1 overflow-hidden">
        {showPreview && previewData ? (
          <TablePreview onClose={() => setShowPreview(false)} />
        ) : selectedTable ? (
          <TableDetails onClose={() => useSchemaStore.getState().selectTable(null)} />
        ) : (
          <TableBrowser onPreview={handlePreview} />
        )}
      </div>

      {/* Preview Toggle */}
      {selectedTable && !showPreview && (
        <div className="border-t border-gray-200 dark:border-gray-700 p-2">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-center gap-2"
            onClick={() => handlePreview(selectedTable)}
            disabled={isLoadingPreview}
          >
            <Eye className="w-4 h-4" />
            Preview Data
          </Button>
        </div>
      )}

      {/* Resize Handle */}
      <div
        className="absolute top-0 right-0 w-1 h-full cursor-col-resize group hover:bg-purple-500/50 transition-colors"
        onMouseDown={startResizing}
      >
        <div
          className={`absolute top-1/2 -translate-y-1/2 -right-1.5 w-4 h-8 flex items-center justify-center rounded bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-600 opacity-0 group-hover:opacity-100 transition-opacity ${
            isResizing ? 'opacity-100 bg-purple-100 dark:bg-purple-900/30 border-purple-400' : ''
          }`}
        >
          <GripVertical className="w-3 h-3 text-gray-400" />
        </div>
      </div>
    </div>
  );
}

function ChatApp() {
  const { sendMessage, cancelSend, isLoading } = useChat();
  const { clearMessages, messages } = useChatStore();
  const { activeConnectionId } = useConnectionStore();
  const [showConnectionSettings, setShowConnectionSettings] = useState(false);

  // Fetch connections on mount
  const { refetch: refetchConnections } = useConnections();

  // WebSocket connection for real-time notifications
  const { isConnected: wsConnected } = useWebSocket(activeConnectionId);

  useEffect(() => {
    refetchConnections();
  }, [refetchConnections]);

  const handleClearChat = () => {
    if (confirm('Are you sure you want to clear all messages?')) {
      clearMessages();
    }
  };

  return (
    <div className="flex h-screen bg-gradient-to-br from-gray-50 via-white to-gray-50 dark:from-gray-950 dark:via-gray-900 dark:to-gray-950">
      {/* Sidebar */}
      <Sidebar />

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="border-b border-gray-200 dark:border-gray-800 bg-white/80 dark:bg-gray-900/80 backdrop-blur-sm">
          <div className="px-4 sm:px-6 lg:px-8 py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-purple-600 to-blue-600 flex items-center justify-center shadow-lg">
                  <svg
                    className="w-6 h-6 text-white"
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
                <div>
                  <h1 className="text-xl font-bold bg-gradient-to-r from-purple-600 to-blue-600 bg-clip-text text-transparent">
                    Text2SQL
                  </h1>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Natural Language to SQL
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                {/* WebSocket Connection Indicator */}
                {activeConnectionId && (
                  <div
                    className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${
                      wsConnected
                        ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400'
                    }`}
                    title={wsConnected ? 'Real-time updates active' : 'Connecting...'}
                  >
                    {wsConnected ? (
                      <Wifi className="w-3 h-3" />
                    ) : (
                      <WifiOff className="w-3 h-3" />
                    )}
                    <span>{wsConnected ? 'Live' : 'Offline'}</span>
                  </div>
                )}

                <ConnectionStatus
                  onOpenSettings={() => setShowConnectionSettings(true)}
                />

                {messages.length > 0 && (
                  <Button
                    onClick={handleClearChat}
                    variant="ghost"
                    size="sm"
                    className="gap-2"
                  >
                    <Trash2 className="w-4 h-4" />
                    Clear Chat
                  </Button>
                )}
              </div>
            </div>
          </div>
        </header>

        {/* Chat Container */}
        <ChatContainer />

        {/* Input Area */}
        <ChatInput onSend={sendMessage} onCancel={cancelSend} isLoading={isLoading} />
      </div>

      {/* Modals */}
      <ConnectionSettingsModal
        isOpen={showConnectionSettings}
        onClose={() => setShowConnectionSettings(false)}
      />
      <ConnectionModal />

      {/* Toast Notifications */}
      <ToastContainer />
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ChatApp />
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
