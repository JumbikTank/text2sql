import axios, { AxiosInstance, AxiosError } from 'axios';
import type { Message, MessagesRequest, ApiError } from '@/types/message';
import type {
  DatabaseConnectionConfig,
  ConnectionTestResponse,
  ConnectionListResponse,
  TableInfo,
  TableDetails,
  TablePreviewResponse,
} from '@/types/schema';

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: '/api',
      timeout: 60000, // 60 seconds for LLM responses
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Response interceptor for error handling
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError<ApiError>) => {
        const apiError: ApiError = {
          error: error.response?.data?.error || error.message || 'An error occurred',
          detail: error.response?.data?.detail,
          status_code: error.response?.status,
        };
        return Promise.reject(apiError);
      }
    );
  }

  /**
   * Send messages to the backend and get AI response.
   * Pass an AbortSignal to allow cancellation.
   */
  async sendMessages(messages: Message[], signal?: AbortSignal): Promise<Message> {
    const request: MessagesRequest = { messages };
    const response = await this.client.post<Message>('/messages', request, { signal });
    return response.data;
  }

  /**
   * Health check endpoint
   */
  async healthCheck(): Promise<{ status: string }> {
    const response = await this.client.get('/health');
    return response.data;
  }

  /**
   * Download CSV file
   */
  async downloadCsv(url: string): Promise<Blob> {
    const response = await axios.get(url, {
      responseType: 'blob',
    });
    return response.data;
  }

  /**
   * Execute SQL query directly (for replay functionality).
   * Uses longer timeout since DB queries can take time. Accepts an AbortSignal
   * for cancellation.
   */
  async executeSql(sql: string, signal?: AbortSignal): Promise<Message> {
    const response = await this.client.post<Message>('/sql', { sql }, {
      timeout: 300000, // 5 minutes for SQL queries
      signal,
    });
    return response.data;
  }

  // Connection Management APIs

  /**
   * Test a database connection
   */
  async testConnection(config: DatabaseConnectionConfig): Promise<ConnectionTestResponse> {
    const response = await this.client.post<ConnectionTestResponse>('/connections/test', config);
    return response.data;
  }

  /**
   * List all saved connections
   */
  async listConnections(): Promise<ConnectionListResponse> {
    const response = await this.client.get<ConnectionListResponse>('/connections');
    return response.data;
  }

  /**
   * Save a new connection
   */
  async saveConnection(config: DatabaseConnectionConfig): Promise<DatabaseConnectionConfig> {
    const response = await this.client.post<DatabaseConnectionConfig>('/connections', config);
    return response.data;
  }

  /**
   * Get a specific connection by ID
   */
  async getConnection(id: string): Promise<DatabaseConnectionConfig> {
    const response = await this.client.get<DatabaseConnectionConfig>(`/connections/${id}`);
    return response.data;
  }

  /**
   * Update an existing connection
   */
  async updateConnection(id: string, config: DatabaseConnectionConfig): Promise<DatabaseConnectionConfig> {
    const response = await this.client.put<DatabaseConnectionConfig>(`/connections/${id}`, config);
    return response.data;
  }

  /**
   * Delete a connection
   */
  async deleteConnection(id: string): Promise<void> {
    await this.client.delete(`/connections/${id}`);
  }

  /**
   * Set the active connection
   */
  async activateConnection(id: string): Promise<void> {
    await this.client.post(`/connections/${id}/activate`);
  }

  // Schema Browsing APIs

  /**
   * List tables in a schema
   */
  async listTables(schemaName: string = 'public'): Promise<TableInfo[]> {
    const response = await this.client.get<TableInfo[]>('/schema/tables', {
      params: { schema_name: schemaName },
    });
    return response.data;
  }

  /**
   * Get table details including columns
   */
  async getTableDetails(tableName: string, schemaName: string = 'public'): Promise<TableDetails> {
    const response = await this.client.get<TableDetails>(`/schema/tables/${tableName}`, {
      params: { schema_name: schemaName },
    });
    return response.data;
  }

  /**
   * Preview table data
   */
  async previewTable(
    tableName: string,
    schemaName: string = 'public',
    limit: number = 50
  ): Promise<TablePreviewResponse> {
    const response = await this.client.post<TablePreviewResponse>('/schema/preview', {
      schema_name: schemaName,
      table_name: tableName,
      limit,
    });
    return response.data;
  }
}

export const apiClient = new ApiClient();
