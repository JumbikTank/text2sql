import { Database, Settings } from 'lucide-react';
import { useConnectionStore } from '@/store/connectionStore';

interface ConnectionStatusProps {
  onOpenSettings: () => void;
}

export function ConnectionStatus({ onOpenSettings }: ConnectionStatusProps) {
  const { connections, activeConnectionId } = useConnectionStore();

  const activeConnection = connections.find((c) => c.id === activeConnectionId);

  return (
    <button
      onClick={onOpenSettings}
      className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
    >
      <Database
        className={`w-4 h-4 ${
          activeConnection ? 'text-green-500' : 'text-gray-400'
        }`}
      />
      <span className="text-sm text-gray-700 dark:text-gray-300">
        {activeConnection ? (
          <span className="flex items-center gap-1.5">
            <span className="font-medium">{activeConnection.name}</span>
            <span className="text-gray-400 text-xs">
              {activeConnection.host}:{activeConnection.port}
            </span>
          </span>
        ) : (
          'No connection'
        )}
      </span>
      <Settings className="w-4 h-4 text-gray-400" />
    </button>
  );
}
