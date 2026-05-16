import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TableBrowser } from '@/components/schema/TableBrowser';
import { useSchemaStore } from '@/store/schemaStore';
import { useConnectionStore } from '@/store/connectionStore';

// Mock the useSchema hook
vi.mock('@/hooks/useSchema', () => ({
  useSchema: () => ({
    tables: [
      {
        schema_name: 'public',
        table_name: 'users',
        table_type: 'BASE TABLE',
        row_count_estimate: 1000,
      },
      {
        schema_name: 'public',
        table_name: 'orders',
        table_type: 'BASE TABLE',
        row_count_estimate: 5000,
      },
      {
        schema_name: 'public',
        table_name: 'user_summary',
        table_type: 'VIEW',
        row_count_estimate: null,
      },
    ],
    isLoadingTables: false,
    refetchTables: vi.fn(),
  }),
}));

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe('TableBrowser', () => {
  const mockOnPreview = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useSchemaStore.setState({
      tables: [],
      selectedTable: null,
      selectedSchema: 'public',
    });
    useConnectionStore.setState({
      connections: [],
      activeConnectionId: 'conn-1',
    });
  });

  it('shows connect message when no active connection', () => {
    useConnectionStore.setState({
      activeConnectionId: null,
    });

    renderWithProviders(<TableBrowser onPreview={mockOnPreview} />);

    expect(screen.getByText(/connect to a database/i)).toBeInTheDocument();
  });

  it('renders table list when connected', () => {
    renderWithProviders(<TableBrowser onPreview={mockOnPreview} />);

    expect(screen.getByText('users')).toBeInTheDocument();
    expect(screen.getByText('orders')).toBeInTheDocument();
    expect(screen.getByText('user_summary')).toBeInTheDocument();
  });

  it('shows view badge for views', () => {
    renderWithProviders(<TableBrowser onPreview={mockOnPreview} />);

    expect(screen.getByText('view')).toBeInTheDocument();
  });

  it('shows row count estimates', () => {
    renderWithProviders(<TableBrowser onPreview={mockOnPreview} />);

    // Check for row count indicators (format may vary by locale)
    expect(screen.getByText(/~1/)).toBeInTheDocument();
    expect(screen.getByText(/~5/)).toBeInTheDocument();
  });

  it('shows table count summary', () => {
    renderWithProviders(<TableBrowser onPreview={mockOnPreview} />);

    expect(screen.getByText(/2 tables, 1 views/i)).toBeInTheDocument();
  });

  it('calls onPreview when preview button is clicked', async () => {
    const user = userEvent.setup();

    renderWithProviders(<TableBrowser onPreview={mockOnPreview} />);

    // Find the first preview button (on users table)
    const previewButtons = screen.getAllByTitle('Preview data');
    await user.click(previewButtons[0]);

    expect(mockOnPreview).toHaveBeenCalledWith('users');
  });

  it('selects table when clicked', async () => {
    const user = userEvent.setup();

    renderWithProviders(<TableBrowser onPreview={mockOnPreview} />);

    await user.click(screen.getByText('orders'));

    expect(useSchemaStore.getState().selectedTable).toBe('orders');
  });
});
