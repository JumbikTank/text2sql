import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useConnections } from '@/hooks/useConnection';
import { apiClient } from '@/services/api';
import { useConnectionStore } from '@/store/connectionStore';
import React from 'react';

// Mock the API client
vi.mock('@/services/api', () => ({
  apiClient: {
    listConnections: vi.fn(),
    testConnection: vi.fn(),
    saveConnection: vi.fn(),
    updateConnection: vi.fn(),
    deleteConnection: vi.fn(),
    activateConnection: vi.fn(),
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

describe('useConnections', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useConnectionStore.setState({
      connections: [],
      activeConnectionId: null,
      isLoading: false,
      error: null,
    });
  });

  it('fetches connections on mount', async () => {
    const mockConnections = {
      connections: [
        {
          id: 'conn-1',
          name: 'Test DB',
          host: 'localhost',
          port: 5432,
          database: 'testdb',
          username: 'user',
          password: '********',
          ssl_mode: 'disable',
        },
      ],
      active_connection_id: 'conn-1',
    };

    vi.mocked(apiClient.listConnections).mockResolvedValue(mockConnections);

    const { result } = renderHook(() => useConnections(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.connections).toHaveLength(1);
    });

    expect(apiClient.listConnections).toHaveBeenCalled();
    expect(result.current.activeConnectionId).toBe('conn-1');
  });

  it('tests connection successfully', async () => {
    const mockTestResult = {
      if_successful: true,
      message: 'Connection successful',
      server_version: 'PostgreSQL 15.0',
      latency_ms: 25,
    };

    vi.mocked(apiClient.testConnection).mockResolvedValue(mockTestResult);
    vi.mocked(apiClient.listConnections).mockResolvedValue({
      connections: [],
      active_connection_id: null,
    });

    const { result } = renderHook(() => useConnections(), {
      wrapper: createWrapper(),
    });

    const config = {
      name: 'Test',
      host: 'localhost',
      port: 5432,
      database: 'testdb',
      username: 'user',
      password: 'pass',
      ssl_mode: 'disable' as const,
    };

    const testResult = await result.current.testConnection(config);

    expect(testResult.if_successful).toBe(true);
    expect(testResult.server_version).toBe('PostgreSQL 15.0');
  });

  it('saves connection successfully', async () => {
    const savedConnection = {
      id: 'new-id',
      name: 'New Connection',
      host: 'localhost',
      port: 5432,
      database: 'newdb',
      username: 'user',
      password: '********',
      ssl_mode: 'disable' as const,
    };

    vi.mocked(apiClient.saveConnection).mockResolvedValue(savedConnection);
    vi.mocked(apiClient.listConnections).mockResolvedValue({
      connections: [],
      active_connection_id: null,
    });

    const { result } = renderHook(() => useConnections(), {
      wrapper: createWrapper(),
    });

    const config = {
      name: 'New Connection',
      host: 'localhost',
      port: 5432,
      database: 'newdb',
      username: 'user',
      password: 'pass',
      ssl_mode: 'disable' as const,
    };

    await result.current.saveConnection(config);

    expect(apiClient.saveConnection).toHaveBeenCalledWith(config);
  });

  it('activates connection successfully', async () => {
    vi.mocked(apiClient.activateConnection).mockResolvedValue(undefined);
    vi.mocked(apiClient.listConnections).mockResolvedValue({
      connections: [
        {
          id: 'conn-1',
          name: 'Test',
          host: 'localhost',
          port: 5432,
          database: 'testdb',
          username: 'user',
          password: '********',
          ssl_mode: 'disable',
        },
      ],
      active_connection_id: null,
    });

    const { result } = renderHook(() => useConnections(), {
      wrapper: createWrapper(),
    });

    await result.current.activateConnection('conn-1');

    // Verify the API was called with correct ID
    expect(apiClient.activateConnection).toHaveBeenCalledWith('conn-1');
  });

  it('deletes connection successfully', async () => {
    vi.mocked(apiClient.deleteConnection).mockResolvedValue(undefined);
    vi.mocked(apiClient.listConnections).mockResolvedValue({
      connections: [],
      active_connection_id: null,
    });

    // Set initial state
    useConnectionStore.setState({
      connections: [
        {
          id: 'conn-1',
          name: 'Test',
          host: 'localhost',
          port: 5432,
          database: 'testdb',
          username: 'user',
          password: '********',
          ssl_mode: 'disable',
        },
      ],
    });

    const { result } = renderHook(() => useConnections(), {
      wrapper: createWrapper(),
    });

    await result.current.deleteConnection('conn-1');

    expect(apiClient.deleteConnection).toHaveBeenCalledWith('conn-1');
  });
});
