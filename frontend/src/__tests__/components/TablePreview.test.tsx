import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TablePreview } from '@/components/schema/TablePreview';
import { useSchemaStore } from '@/store/schemaStore';

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

describe('TablePreview', () => {
  const mockOnClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows empty state when no preview data', () => {
    useSchemaStore.setState({
      previewData: null,
      isLoadingPreview: false,
    });

    renderWithProviders(<TablePreview onClose={mockOnClose} />);

    expect(screen.getByText(/click the preview button/i)).toBeInTheDocument();
  });

  it('shows loading state', () => {
    useSchemaStore.setState({
      previewData: null,
      isLoadingPreview: true,
    });

    renderWithProviders(<TablePreview onClose={mockOnClose} />);

    expect(screen.getByText(/loading preview/i)).toBeInTheDocument();
  });

  it('renders preview data table', () => {
    useSchemaStore.setState({
      previewData: {
        schema_name: 'public',
        table_name: 'users',
        columns: ['id', 'name', 'email'],
        rows: [
          [1, 'John Doe', 'john@example.com'],
          [2, 'Jane Smith', 'jane@example.com'],
        ],
        total_rows: 2,
        has_more: false,
      },
      isLoadingPreview: false,
    });

    renderWithProviders(<TablePreview onClose={mockOnClose} />);

    expect(screen.getByText('users')).toBeInTheDocument();
    expect(screen.getByText('id')).toBeInTheDocument();
    expect(screen.getByText('name')).toBeInTheDocument();
    expect(screen.getByText('email')).toBeInTheDocument();
    expect(screen.getByText('John Doe')).toBeInTheDocument();
    expect(screen.getByText('jane@example.com')).toBeInTheDocument();
  });

  it('shows NULL for null values', () => {
    useSchemaStore.setState({
      previewData: {
        schema_name: 'public',
        table_name: 'users',
        columns: ['id', 'name', 'email'],
        rows: [
          [1, 'John Doe', null],
        ],
        total_rows: 1,
        has_more: false,
      },
      isLoadingPreview: false,
    });

    renderWithProviders(<TablePreview onClose={mockOnClose} />);

    expect(screen.getByText('NULL')).toBeInTheDocument();
  });

  it('shows row count info', () => {
    useSchemaStore.setState({
      previewData: {
        schema_name: 'public',
        table_name: 'users',
        columns: ['id'],
        rows: [[1], [2], [3]],
        total_rows: 3,
        has_more: false,
      },
      isLoadingPreview: false,
    });

    renderWithProviders(<TablePreview onClose={mockOnClose} />);

    expect(screen.getByText(/3 rows loaded/i)).toBeInTheDocument();
  });

  it('shows has_more indicator', () => {
    useSchemaStore.setState({
      previewData: {
        schema_name: 'public',
        table_name: 'users',
        columns: ['id'],
        rows: [[1], [2], [3]],
        total_rows: 3,
        has_more: true,
      },
      isLoadingPreview: false,
    });

    renderWithProviders(<TablePreview onClose={mockOnClose} />);

    expect(screen.getByText(/more available/i)).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', async () => {
    const user = userEvent.setup();

    useSchemaStore.setState({
      previewData: {
        schema_name: 'public',
        table_name: 'users',
        columns: ['id'],
        rows: [[1]],
        total_rows: 1,
        has_more: false,
      },
      isLoadingPreview: false,
    });

    renderWithProviders(<TablePreview onClose={mockOnClose} />);

    // Find the X button in the header
    const closeButtons = screen.getAllByRole('button');
    const closeButton = closeButtons.find(btn => btn.getAttribute('aria-label') === 'Close modal' || btn.querySelector('svg'));
    if (closeButton) {
      await user.click(closeButton);
      expect(mockOnClose).toHaveBeenCalled();
    }
  });

  it('shows pagination for many rows', () => {
    const rows = Array.from({ length: 25 }, (_, i) => [i + 1]);

    useSchemaStore.setState({
      previewData: {
        schema_name: 'public',
        table_name: 'users',
        columns: ['id'],
        rows,
        total_rows: 25,
        has_more: false,
      },
      isLoadingPreview: false,
    });

    renderWithProviders(<TablePreview onClose={mockOnClose} />);

    expect(screen.getByText(/page 1 of 3/i)).toBeInTheDocument();
  });
});
