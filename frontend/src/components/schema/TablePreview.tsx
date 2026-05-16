import { useState } from 'react';
import { Loader2, X, ChevronLeft, ChevronRight, Table } from 'lucide-react';
import { useSchemaStore } from '@/store/schemaStore';
import { Button } from '@/components/ui/Button';
import { cn } from '@/utils/cn';

interface TablePreviewProps {
  onClose?: () => void;
}

export function TablePreview({ onClose }: TablePreviewProps) {
  const { previewData, isLoadingPreview } = useSchemaStore();
  const [currentPage, setCurrentPage] = useState(0);
  const rowsPerPage = 10;

  if (isLoadingPreview) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-2 text-gray-500">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>Loading preview...</span>
        </div>
      </div>
    );
  }

  if (!previewData) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 dark:text-gray-400">
        <div className="text-center">
          <Table className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>Click the preview button on a table to see data</p>
        </div>
      </div>
    );
  }

  const totalPages = Math.ceil(previewData.rows.length / rowsPerPage);
  const startIndex = currentPage * rowsPerPage;
  const endIndex = startIndex + rowsPerPage;
  const visibleRows = previewData.rows.slice(startIndex, endIndex);

  const formatCellValue = (value: unknown): string => {
    if (value === null) return 'NULL';
    if (value === undefined) return '';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 truncate" title={previewData.table_name}>
            {previewData.table_name}
          </h3>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {previewData.schema_name} &middot; {previewData.total_rows} rows loaded
            {previewData.has_more && ' (more available)'}
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

      <div className="flex-1 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-gray-50 dark:bg-gray-800">
            <tr>
              {previewData.columns.map((column, index) => (
                <th
                  key={index}
                  className="px-3 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider whitespace-nowrap border-b border-gray-200 dark:border-gray-700"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
            {visibleRows.map((row, rowIndex) => (
              <tr
                key={startIndex + rowIndex}
                className="hover:bg-gray-50 dark:hover:bg-gray-800/50"
              >
                {row.map((cell, cellIndex) => (
                  <td
                    key={cellIndex}
                    className={cn(
                      'px-3 py-2 whitespace-nowrap font-mono text-xs',
                      cell === null
                        ? 'text-gray-400 dark:text-gray-500 italic'
                        : 'text-gray-900 dark:text-gray-100'
                    )}
                    title={formatCellValue(cell)}
                  >
                    <span className="block max-w-[200px] truncate">
                      {formatCellValue(cell)}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            Showing {startIndex + 1}-{Math.min(endIndex, previewData.rows.length)} of{' '}
            {previewData.total_rows}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
              disabled={currentPage === 0}
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="text-sm text-gray-600 dark:text-gray-400">
              Page {currentPage + 1} of {totalPages}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setCurrentPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={currentPage >= totalPages - 1}
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
