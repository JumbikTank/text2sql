import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConnectionForm } from '@/components/connection/ConnectionForm';

// Mock the useConnections hook
vi.mock('@/hooks/useConnection', () => ({
  useConnections: () => ({
    testConnection: vi.fn().mockResolvedValue({
      if_successful: true,
      message: 'Connection successful',
      server_version: 'PostgreSQL 15.0',
      latency_ms: 25,
    }),
    isTestingConnection: false,
    testResult: null,
    saveConnection: vi.fn().mockResolvedValue({ id: 'test-id', name: 'Test' }),
    isSavingConnection: false,
    updateConnection: vi.fn().mockResolvedValue({ id: 'test-id', name: 'Updated' }),
    isUpdatingConnection: false,
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

describe('ConnectionForm', () => {
  const mockOnSuccess = vi.fn();
  const mockOnCancel = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders all form fields', () => {
    renderWithProviders(
      <ConnectionForm onSuccess={mockOnSuccess} onCancel={mockOnCancel} />
    );

    expect(screen.getByLabelText(/connection name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/host/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/port/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/database/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/ssl mode/i)).toBeInTheDocument();
  });

  it('shows validation errors for empty required fields', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <ConnectionForm onSuccess={mockOnSuccess} onCancel={mockOnCancel} />
    );

    // Try to save without filling required fields
    await user.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(screen.getByText(/connection name is required/i)).toBeInTheDocument();
    });
  });

  it('validates port range', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <ConnectionForm onSuccess={mockOnSuccess} onCancel={mockOnCancel} />
    );

    const portInput = screen.getByLabelText(/port/i);
    await user.clear(portInput);
    await user.type(portInput, '99999');

    await user.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(screen.getByText(/port must be between 1 and 65535/i)).toBeInTheDocument();
    });
  });

  it('calls onCancel when cancel button is clicked', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <ConnectionForm onSuccess={mockOnSuccess} onCancel={mockOnCancel} />
    );

    await user.click(screen.getByRole('button', { name: /cancel/i }));

    expect(mockOnCancel).toHaveBeenCalled();
  });

  it('has test connection button', () => {
    renderWithProviders(
      <ConnectionForm onSuccess={mockOnSuccess} onCancel={mockOnCancel} />
    );

    expect(screen.getByRole('button', { name: /test connection/i })).toBeInTheDocument();
  });

  it('pre-fills form when initialData is provided', () => {
    const initialData = {
      id: 'test-id',
      name: 'My Database',
      host: 'db.example.com',
      port: 5433,
      database: 'mydb',
      username: 'admin',
      password: 'secret',
      ssl_mode: 'require' as const,
    };

    renderWithProviders(
      <ConnectionForm
        initialData={initialData}
        onSuccess={mockOnSuccess}
        onCancel={mockOnCancel}
      />
    );

    expect(screen.getByLabelText(/connection name/i)).toHaveValue('My Database');
    expect(screen.getByLabelText(/host/i)).toHaveValue('db.example.com');
    expect(screen.getByLabelText(/port/i)).toHaveValue(5433);
    expect(screen.getByLabelText(/database/i)).toHaveValue('mydb');
    expect(screen.getByLabelText(/username/i)).toHaveValue('admin');
    // Password should be empty for security
    expect(screen.getByLabelText(/password/i)).toHaveValue('');
  });

  it('shows Update button when editing existing connection', () => {
    const initialData = {
      id: 'test-id',
      name: 'Existing Connection',
      host: 'localhost',
      port: 5432,
      database: 'testdb',
      username: 'user',
      password: 'pass',
      ssl_mode: 'disable' as const,
    };

    renderWithProviders(
      <ConnectionForm
        initialData={initialData}
        onSuccess={mockOnSuccess}
        onCancel={mockOnCancel}
      />
    );

    expect(screen.getByRole('button', { name: /update/i })).toBeInTheDocument();
  });
});
