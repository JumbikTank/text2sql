import { Database, Edit, Trash2, Check, MoreVertical, Plus } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { useConnections } from '@/hooks/useConnection';
import { useConnectionStore } from '@/store/connectionStore';
import type { DatabaseConnectionConfig } from '@/types/schema';
import { useState, useRef, useEffect } from 'react';

interface ConnectionListProps {
  onEdit: (connection: DatabaseConnectionConfig) => void;
  onAddNew: () => void;
}

function ConnectionMenu({
  connection,
  isActive,
  onActivate,
  onEdit,
  onDelete,
}: {
  connection: DatabaseConnectionConfig;
  isActive: boolean;
  onActivate: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
      >
        <MoreVertical className="w-4 h-4 text-gray-500" />
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-1 w-40 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 z-10">
          {!isActive && (
            <button
              onClick={() => {
                onActivate();
                setIsOpen(false);
              }}
              className="w-full px-3 py-2 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2"
            >
              <Check className="w-4 h-4" />
              Set Active
            </button>
          )}
          <button
            onClick={() => {
              onEdit();
              setIsOpen(false);
            }}
            className="w-full px-3 py-2 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2"
          >
            <Edit className="w-4 h-4" />
            Edit
          </button>
          <button
            onClick={() => {
              if (confirm(`Delete connection "${connection.name}"?`)) {
                onDelete();
              }
              setIsOpen(false);
            }}
            className="w-full px-3 py-2 text-left text-sm text-red-600 dark:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2"
          >
            <Trash2 className="w-4 h-4" />
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

export function ConnectionList({ onEdit, onAddNew }: ConnectionListProps) {
  const { connections, activeConnectionId } = useConnectionStore();
  const { activateConnection, deleteConnection } = useConnections();

  if (connections.length === 0) {
    return (
      <div className="text-center py-8">
        <Database className="w-12 h-12 mx-auto text-gray-400 mb-3" />
        <p className="text-gray-500 dark:text-gray-400 mb-4">No connections yet</p>
        <Button onClick={onAddNew} size="sm">
          <Plus className="w-4 h-4 mr-2" />
          Add Connection
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">
          Connections
        </h3>
        <Button variant="ghost" size="sm" onClick={onAddNew}>
          <Plus className="w-4 h-4" />
        </Button>
      </div>

      {connections.map((connection) => {
        const isActive = connection.id === activeConnectionId;

        return (
          <div
            key={connection.id}
            className={`p-3 rounded-lg border transition-colors ${
              isActive
                ? 'border-purple-500 bg-purple-50 dark:bg-purple-900/20'
                : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3 min-w-0">
                <Database
                  className={`w-5 h-5 flex-shrink-0 ${
                    isActive ? 'text-purple-600' : 'text-gray-400'
                  }`}
                />
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-gray-900 dark:text-gray-100 truncate">
                      {connection.name}
                    </p>
                    {isActive && (
                      <span className="text-xs px-1.5 py-0.5 bg-purple-100 dark:bg-purple-800 text-purple-700 dark:text-purple-300 rounded">
                        Active
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                    {connection.host}:{connection.port}/{connection.database}
                  </p>
                </div>
              </div>

              <ConnectionMenu
                connection={connection}
                isActive={isActive}
                onActivate={() => connection.id && activateConnection(connection.id)}
                onEdit={() => onEdit(connection)}
                onDelete={() => connection.id && deleteConnection(connection.id)}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
