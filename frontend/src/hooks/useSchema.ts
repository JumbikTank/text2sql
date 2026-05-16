import { useQuery, useMutation } from '@tanstack/react-query';
import { apiClient } from '@/services/api';
import { useSchemaStore } from '@/store/schemaStore';
import { useConnectionStore } from '@/store/connectionStore';

export function useSchema() {
  const {
    selectedSchema,
    selectedTable,
    setTables,
    selectTable,
    setTableDetails,
    setPreviewData,
    setLoadingTables,
    setLoadingDetails,
    setLoadingPreview,
    setError,
    clearError,
  } = useSchemaStore();

  const { activeConnectionId } = useConnectionStore();

  const tablesQuery = useQuery({
    queryKey: ['tables', selectedSchema, activeConnectionId],
    queryFn: async () => {
      setLoadingTables(true);
      clearError();
      try {
        const tables = await apiClient.listTables(selectedSchema);
        setTables(tables);
        return tables;
      } catch (error: any) {
        setError(error.error || 'Failed to load tables');
        throw error;
      } finally {
        setLoadingTables(false);
      }
    },
    enabled: !!activeConnectionId,
    staleTime: 30000,
  });

  const tableDetailsQuery = useQuery({
    queryKey: ['tableDetails', selectedTable, selectedSchema, activeConnectionId],
    queryFn: async () => {
      if (!selectedTable) return null;
      setLoadingDetails(true);
      clearError();
      try {
        const details = await apiClient.getTableDetails(selectedTable, selectedSchema);
        setTableDetails(details);
        return details;
      } catch (error: any) {
        setError(error.error || 'Failed to load table details');
        throw error;
      } finally {
        setLoadingDetails(false);
      }
    },
    enabled: !!selectedTable && !!activeConnectionId,
    staleTime: 30000,
  });

  const previewMutation = useMutation({
    mutationFn: async ({
      tableName,
      schemaName,
      limit,
    }: {
      tableName: string;
      schemaName?: string;
      limit?: number;
    }) => {
      setLoadingPreview(true);
      clearError();
      try {
        const preview = await apiClient.previewTable(
          tableName,
          schemaName || selectedSchema,
          limit || 50
        );
        setPreviewData(preview);
        return preview;
      } catch (error: any) {
        setError(error.error || 'Failed to load table preview');
        throw error;
      } finally {
        setLoadingPreview(false);
      }
    },
  });

  return {
    tables: tablesQuery.data || [],
    isLoadingTables: tablesQuery.isLoading,
    tableDetails: tableDetailsQuery.data,
    isLoadingDetails: tableDetailsQuery.isLoading,
    selectedTable,
    selectTable,
    previewTable: (tableName: string, schemaName?: string, limit?: number) =>
      previewMutation.mutateAsync({ tableName, schemaName, limit }),
    isLoadingPreview: previewMutation.isPending,
    previewData: previewMutation.data,
    refetchTables: tablesQuery.refetch,
    refetchDetails: tableDetailsQuery.refetch,
  };
}
