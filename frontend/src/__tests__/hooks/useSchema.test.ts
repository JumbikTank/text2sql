import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useSchema } from '@/hooks/useSchema';
import { apiClient } from '@/services/api';
import { useSchemaStore } from '@/store/schemaStore';
import { useConnectionStore } from '@/store/connectionStore';
import React from 'react';

// Mock the API client
vi.mock('@/services/api', () => ({
  apiClient: {
    listTables: vi.fn(),
    getTableDetails: vi.fn(),
    previewTable: vi.fn(),
  },
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

describe('useSchema', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSchemaStore.setState({
      tables: [],
      selectedTable: null,
      selectedSchema: 'public',
      tableDetails: null,
      previewData: null,
      isLoadingTables: false,
      isLoadingDetails: false,
      isLoadingPreview: false,
      error: null,
    });
    useConnectionStore.setState({
      connections: [],
      activeConnectionId: 'conn-1',
    });
  });

  it('fetches tables when active connection exists', async () => {
    const mockTables = [
      {
        schema_name: 'public',
        table_name: 'users',
        table_type: 'BASE TABLE' as const,
        row_count_estimate: 1000,
      },
      {
        schema_name: 'public',
        table_name: 'orders',
        table_type: 'BASE TABLE' as const,
        row_count_estimate: 5000,
      },
    ];

    vi.mocked(apiClient.listTables).mockResolvedValue(mockTables);

    const { result } = renderHook(() => useSchema(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.tables).toHaveLength(2);
    });

    expect(apiClient.listTables).toHaveBeenCalledWith('public');
  });

  it('does not fetch tables when no active connection', async () => {
    useConnectionStore.setState({
      activeConnectionId: null,
    });

    vi.mocked(apiClient.listTables).mockResolvedValue([]);

    renderHook(() => useSchema(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(apiClient.listTables).not.toHaveBeenCalled();
    });
  });

  it('fetches table details when table is selected', async () => {
    const mockDetails = {
      schema_name: 'public',
      table_name: 'users',
      columns: [
        {
          name: 'id',
          data_type: 'integer',
          if_nullable: false,
          if_primary_key: true,
          if_foreign_key: false,
          foreign_key_reference: null,
        },
        {
          name: 'name',
          data_type: 'varchar',
          if_nullable: true,
          if_primary_key: false,
          if_foreign_key: false,
          foreign_key_reference: null,
        },
      ],
      row_count_estimate: 1000,
    };

    useSchemaStore.setState({
      selectedTable: 'users',
    });

    vi.mocked(apiClient.getTableDetails).mockResolvedValue(mockDetails);
    vi.mocked(apiClient.listTables).mockResolvedValue([]);

    const { result } = renderHook(() => useSchema(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.tableDetails).not.toBeNull();
    });

    expect(apiClient.getTableDetails).toHaveBeenCalledWith('users', 'public');
  });

  it('previews table data', async () => {
    const mockPreview = {
      schema_name: 'public',
      table_name: 'users',
      columns: ['id', 'name', 'email'],
      rows: [
        [1, 'John', 'john@example.com'],
        [2, 'Jane', 'jane@example.com'],
      ],
      total_rows: 2,
      has_more: false,
    };

    vi.mocked(apiClient.previewTable).mockResolvedValue(mockPreview);
    vi.mocked(apiClient.listTables).mockResolvedValue([]);

    const { result } = renderHook(() => useSchema(), {
      wrapper: createWrapper(),
    });

    await result.current.previewTable('users', 'public', 50);

    expect(apiClient.previewTable).toHaveBeenCalledWith('users', 'public', 50);
    expect(useSchemaStore.getState().previewData).not.toBeNull();
  });

  it('selects table', async () => {
    vi.mocked(apiClient.listTables).mockResolvedValue([]);

    const { result } = renderHook(() => useSchema(), {
      wrapper: createWrapper(),
    });

    result.current.selectTable('users');

    expect(useSchemaStore.getState().selectedTable).toBe('users');
  });

  it('handles error when loading tables', async () => {
    vi.mocked(apiClient.listTables).mockRejectedValue({
      error: 'Connection failed',
    });

    renderHook(() => useSchema(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(useSchemaStore.getState().error).not.toBeNull();
    });
  });
});
