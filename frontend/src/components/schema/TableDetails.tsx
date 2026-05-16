import { useEffect } from 'react';
import { Key, Link2, Table, Loader2, X } from 'lucide-react';
import { useSchema } from '@/hooks/useSchema';
import { useSchemaStore } from '@/store/schemaStore';
import { cn } from '@/utils/cn';

interface TableDetailsProps {
  onClose?: () => void;
}

export function TableDetails({ onClose }: TableDetailsProps) {
  const { tableDetails, isLoadingDetails, refetchDetails } = useSchema();
  const { selectedTable, selectedSchema } = useSchemaStore();

  useEffect(() => {
    if (selectedTable) {
      refetchDetails();
    }
  }, [selectedTable, selectedSchema, refetchDetails]);

  if (!selectedTable) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 dark:text-gray-400">
        <div className="text-center">
          <Table className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>Select a table to view details</p>
        </div>
      </div>
    );
  }

  if (isLoadingDetails) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-2 text-gray-500">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>Loading table details...</span>
        </div>
      </div>
    );
  }

  if (!tableDetails) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 dark:text-gray-400">
        <p>No details available</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 truncate" title={tableDetails.table_name}>
            {tableDetails.table_name}
          </h3>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {tableDetails.schema_name}
            {tableDetails.row_count_estimate && (
              <> &middot; ~{tableDetails.row_count_estimate.toLocaleString()} rows</>
            )}
          </p>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="flex-shrink-0 p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <X className="w-5 h-5 text-gray-500" />
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-gray-50 dark:bg-gray-800">
            <tr className="text-left text-xs text-gray-500 dark:text-gray-400">
              <th className="px-4 py-2 font-medium">Column</th>
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 font-medium">Nullable</th>
              <th className="px-4 py-2 font-medium">Keys</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {tableDetails.columns.map((column) => (
              <tr
                key={column.name}
                className="hover:bg-gray-50 dark:hover:bg-gray-800/50"
              >
                <td className="px-4 py-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        'text-sm font-mono',
                        column.if_primary_key
                          ? 'text-yellow-600 dark:text-yellow-500 font-medium'
                          : 'text-gray-900 dark:text-gray-100'
                      )}
                    >
                      {column.name}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-2">
                  <span className="text-sm font-mono text-gray-600 dark:text-gray-400">
                    {column.data_type}
                  </span>
                </td>
                <td className="px-4 py-2">
                  <span
                    className={cn(
                      'text-xs px-1.5 py-0.5 rounded',
                      column.if_nullable
                        ? 'bg-gray-100 dark:bg-gray-800 text-gray-500'
                        : 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400'
                    )}
                  >
                    {column.if_nullable ? 'NULL' : 'NOT NULL'}
                  </span>
                </td>
                <td className="px-4 py-2">
                  <div className="flex items-center gap-1">
                    {column.if_primary_key && (
                      <span
                        className="flex items-center gap-1 text-xs px-1.5 py-0.5 bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-400 rounded"
                        title="Primary Key"
                      >
                        <Key className="w-3 h-3" />
                        PK
                      </span>
                    )}
                    {column.if_foreign_key && (
                      <span
                        className="flex items-center gap-1 text-xs px-1.5 py-0.5 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 rounded"
                        title={column.foreign_key_reference || 'Foreign Key'}
                      >
                        <Link2 className="w-3 h-3" />
                        FK
                      </span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {tableDetails.columns.some((c) => c.if_foreign_key) && (
        <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
          <h4 className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
            Foreign Key References
          </h4>
          <div className="space-y-1">
            {tableDetails.columns
              .filter((c) => c.if_foreign_key && c.foreign_key_reference)
              .map((column) => (
                <div
                  key={column.name}
                  className="text-xs text-gray-600 dark:text-gray-400"
                >
                  <span className="font-mono text-purple-600 dark:text-purple-400">
                    {column.name}
                  </span>
                  <span className="mx-2">&rarr;</span>
                  <span className="font-mono">{column.foreign_key_reference}</span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
