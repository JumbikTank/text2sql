import { useEffect } from 'react';
import { Table, Eye, RefreshCw, ChevronRight, Layers } from 'lucide-react';
import { useSchema } from '@/hooks/useSchema';
import { useSchemaStore } from '@/store/schemaStore';
import { useConnectionStore } from '@/store/connectionStore';
import { cn } from '@/utils/cn';

interface TableBrowserProps {
  onPreview?: (tableName: string) => void;
}

export function TableBrowser({ onPreview }: TableBrowserProps) {
  const { tables, isLoadingTables, refetchTables } = useSchema();
  const { selectedTable, selectTable, selectedSchema } = useSchemaStore();
  const { activeConnectionId } = useConnectionStore();

  useEffect(() => {
    if (activeConnectionId) {
      refetchTables();
    }
  }, [activeConnectionId, refetchTables]);

  if (!activeConnectionId) {
    return (
      <div className="p-4 text-center text-gray-500 dark:text-gray-400">
        <Layers className="w-8 h-8 mx-auto mb-2 opacity-50" />
        <p className="text-sm">Connect to a database to browse tables</p>
      </div>
    );
  }

  if (isLoadingTables) {
    return (
      <div className="p-4">
        <div className="flex items-center gap-2 text-gray-500">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading tables...</span>
        </div>
      </div>
    );
  }

  if (tables.length === 0) {
    return (
      <div className="p-4 text-center text-gray-500 dark:text-gray-400">
        <Table className="w-8 h-8 mx-auto mb-2 opacity-50" />
        <p className="text-sm">No tables found in "{selectedSchema}"</p>
        <button
          onClick={() => refetchTables()}
          className="mt-2 text-sm text-purple-600 hover:text-purple-700 dark:text-purple-400 dark:hover:text-purple-300"
        >
          Refresh
        </button>
      </div>
    );
  }

  const baseTableCount = tables.filter((t) => t.table_type === 'BASE TABLE').length;
  const viewCount = tables.filter((t) => t.table_type === 'VIEW').length;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {baseTableCount} tables, {viewCount} views
          </span>
        </div>
        <button
          onClick={() => refetchTables()}
          className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          title="Refresh tables"
        >
          <RefreshCw className="w-4 h-4 text-gray-500" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {tables.map((table) => {
          const isSelected = selectedTable === table.table_name;
          const isView = table.table_type === 'VIEW';

          return (
            <div
              key={`${table.schema_name}.${table.table_name}`}
              className={cn(
                'group flex items-center justify-between px-4 py-2 cursor-pointer transition-colors',
                isSelected
                  ? 'bg-purple-50 dark:bg-purple-900/20 border-l-2 border-purple-500'
                  : 'hover:bg-gray-50 dark:hover:bg-gray-800/50 border-l-2 border-transparent'
              )}
              onClick={() => selectTable(table.table_name)}
            >
              <div className="flex items-center gap-2 min-w-0">
                <Table
                  className={cn(
                    'w-4 h-4 flex-shrink-0',
                    isView ? 'text-blue-500' : 'text-gray-400'
                  )}
                />
                <span
                  className={cn(
                    'text-sm truncate',
                    isSelected
                      ? 'text-purple-700 dark:text-purple-300 font-medium'
                      : 'text-gray-700 dark:text-gray-300'
                  )}
                >
                  {table.table_name}
                </span>
                {isView && (
                  <span className="text-xs px-1 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded">
                    view
                  </span>
                )}
              </div>

              <div className="flex items-center gap-1">
                {table.row_count_estimate && (
                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    ~{table.row_count_estimate.toLocaleString()}
                  </span>
                )}
                {onPreview && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onPreview(table.table_name);
                    }}
                    className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-gray-200 dark:hover:bg-gray-700 transition-all"
                    title="Preview data"
                  >
                    <Eye className="w-4 h-4 text-gray-500" />
                  </button>
                )}
                <ChevronRight
                  className={cn(
                    'w-4 h-4 transition-transform',
                    isSelected
                      ? 'text-purple-500 rotate-90'
                      : 'text-gray-400 opacity-0 group-hover:opacity-100'
                  )}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
