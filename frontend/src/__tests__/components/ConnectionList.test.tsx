import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConnectionList } from '@/components/connection/ConnectionList';
import { useConnectionStore } from '@/store/connectionStore';

// Mock the hooks
vi.mock('@/hooks/useConnection', () => ({
  useConnections: () => ({
    activateConnection: vi.fn().mockResolvedValue(undefined),
    deleteConnection: vi.fn().mockResolvedValue(undefined),
    isLoading: false,
  }),
}));

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe('ConnectionList', () => {
  const mockOnEdit = vi.fn();
  const mockOnAddNew = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    // Reset the store
    useConnectionStore.setState({
      connections: [],
      activeConnectionId: null,
    });
  });

  it('shows empty state when no connections', () => {
    renderWithProviders(
      <ConnectionList onEdit={mockOnEdit} onAddNew={mockOnAddNew} />
    );

    expect(screen.getByText(/no connections yet/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add connection/i })).toBeInTheDocument();
  });

  it('calls onAddNew when add connection button is clicked in empty state', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <ConnectionList onEdit={mockOnEdit} onAddNew={mockOnAddNew} />
    );

    await user.click(screen.getByRole('button', { name: /add connection/i }));

    expect(mockOnAddNew).toHaveBeenCalled();
  });

  it('renders connections list when connections exist', () => {
    useConnectionStore.setState({
      connections: [
        {
          id: 'conn-1',
          name: 'Production DB',
          host: 'prod.example.com',
          port: 5432,
          database: 'proddb',
          username: 'admin',
          password: '********',
          ssl_mode: 'require',
        },
        {
          id: 'conn-2',
          name: 'Development DB',
          host: 'localhost',
          port: 5432,
          database: 'devdb',
          username: 'dev',
          password: '********',
          ssl_mode: 'disable',
        },
      ],
      activeConnectionId: 'conn-1',
    });

    renderWithProviders(
      <ConnectionList onEdit={mockOnEdit} onAddNew={mockOnAddNew} />
    );

    expect(screen.getByText('Production DB')).toBeInTheDocument();
    expect(screen.getByText('Development DB')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('shows connection details', () => {
    useConnectionStore.setState({
      connections: [
        {
          id: 'conn-1',
          name: 'Test DB',
          host: 'test.example.com',
          port: 5433,
          database: 'testdb',
          username: 'testuser',
          password: '********',
          ssl_mode: 'disable',
        },
      ],
      activeConnectionId: null,
    });

    renderWithProviders(
      <ConnectionList onEdit={mockOnEdit} onAddNew={mockOnAddNew} />
    );

    expect(screen.getByText('Test DB')).toBeInTheDocument();
    expect(screen.getByText('test.example.com:5433/testdb')).toBeInTheDocument();
  });

  it('marks active connection', () => {
    useConnectionStore.setState({
      connections: [
        {
          id: 'conn-1',
          name: 'Active Connection',
          host: 'localhost',
          port: 5432,
          database: 'activedb',
          username: 'user',
          password: '********',
          ssl_mode: 'disable',
        },
      ],
      activeConnectionId: 'conn-1',
    });

    renderWithProviders(
      <ConnectionList onEdit={mockOnEdit} onAddNew={mockOnAddNew} />
    );

    expect(screen.getByText('Active')).toBeInTheDocument();
  });
});
