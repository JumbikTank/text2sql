import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/services/api';
import { useConnectionStore } from '@/store/connectionStore';
import type { DatabaseConnectionConfig } from '@/types/schema';

export function useConnections() {
  const queryClient = useQueryClient();
  const {
    setConnections,
    addConnection,
    updateConnection,
    removeConnection,
    setActiveConnectionId,
    setLoading,
    setError,
    clearError,
  } = useConnectionStore();

  const connectionsQuery = useQuery({
    queryKey: ['connections'],
    queryFn: async () => {
      const response = await apiClient.listConnections();
      setConnections(response.connections);
      setActiveConnectionId(response.active_connection_id ?? null);
      return response;
    },
    staleTime: 30000,
  });

  const testConnectionMutation = useMutation({
    mutationFn: (config: DatabaseConnectionConfig) => apiClient.testConnection(config),
    onMutate: () => {
      setLoading(true);
      clearError();
    },
    onSettled: () => setLoading(false),
    onError: (error: any) => {
      setError(error.error || 'Failed to test connection');
    },
  });

  const saveConnectionMutation = useMutation({
    mutationFn: (config: DatabaseConnectionConfig) => apiClient.saveConnection(config),
    onMutate: () => {
      setLoading(true);
      clearError();
    },
    onSuccess: (savedConnection) => {
      addConnection(savedConnection);
      queryClient.invalidateQueries({ queryKey: ['connections'] });
    },
    onSettled: () => setLoading(false),
    onError: (error: any) => {
      setError(error.error || 'Failed to save connection');
    },
  });

  const updateConnectionMutation = useMutation({
    mutationFn: ({ id, config }: { id: string; config: DatabaseConnectionConfig }) =>
      apiClient.updateConnection(id, config),
    onMutate: () => {
      setLoading(true);
      clearError();
    },
    onSuccess: (updatedConnection) => {
      if (updatedConnection.id) {
        updateConnection(updatedConnection.id, updatedConnection);
      }
      queryClient.invalidateQueries({ queryKey: ['connections'] });
    },
    onSettled: () => setLoading(false),
    onError: (error: any) => {
      setError(error.error || 'Failed to update connection');
    },
  });

  const deleteConnectionMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteConnection(id),
    onMutate: () => {
      setLoading(true);
      clearError();
    },
    onSuccess: (_, id) => {
      removeConnection(id);
      queryClient.invalidateQueries({ queryKey: ['connections'] });
    },
    onSettled: () => setLoading(false),
    onError: (error: any) => {
      setError(error.error || 'Failed to delete connection');
    },
  });

  const activateConnectionMutation = useMutation({
    mutationFn: (id: string) => apiClient.activateConnection(id),
    onMutate: () => {
      setLoading(true);
      clearError();
    },
    onSuccess: (_, id) => {
      setActiveConnectionId(id);
      queryClient.invalidateQueries({ queryKey: ['connections'] });
      queryClient.invalidateQueries({ queryKey: ['tables'] });
    },
    onSettled: () => setLoading(false),
    onError: (error: any) => {
      setError(error.error || 'Failed to activate connection');
    },
  });

  return {
    connections: connectionsQuery.data?.connections || [],
    activeConnectionId: connectionsQuery.data?.active_connection_id,
    isLoading: connectionsQuery.isLoading,
    isFetching: connectionsQuery.isFetching,
    error: connectionsQuery.error,
    refetch: connectionsQuery.refetch,
    testConnection: testConnectionMutation.mutateAsync,
    isTestingConnection: testConnectionMutation.isPending,
    testResult: testConnectionMutation.data,
    saveConnection: saveConnectionMutation.mutateAsync,
    isSavingConnection: saveConnectionMutation.isPending,
    updateConnection: (id: string, config: DatabaseConnectionConfig) =>
      updateConnectionMutation.mutateAsync({ id, config }),
    isUpdatingConnection: updateConnectionMutation.isPending,
    deleteConnection: deleteConnectionMutation.mutateAsync,
    isDeletingConnection: deleteConnectionMutation.isPending,
    activateConnection: activateConnectionMutation.mutateAsync,
    isActivatingConnection: activateConnectionMutation.isPending,
  };
}
