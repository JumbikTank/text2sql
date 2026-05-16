export type SslMode = 'disable' | 'require' | 'verify-ca' | 'verify-full';
export type TableType = 'BASE TABLE' | 'VIEW';

export interface DatabaseConnectionConfig {
  id?: string | null;
  name: string;
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  ssl_mode: SslMode;
}

export interface ConnectionTestResponse {
  if_successful: boolean;
  message: string;
  server_version?: string | null;
  latency_ms?: number | null;
}

export interface TableInfo {
  schema_name: string;
  table_name: string;
  table_type: TableType;
  row_count_estimate?: number | null;
}

export interface ColumnInfo {
  name: string;
  data_type: string;
  if_nullable: boolean;
  if_primary_key: boolean;
  if_foreign_key: boolean;
  foreign_key_reference?: string | null;
}

export interface TableDetails {
  schema_name: string;
  table_name: string;
  columns: ColumnInfo[];
  row_count_estimate?: number | null;
}

export interface TablePreviewRequest {
  schema_name?: string;
  table_name: string;
  limit?: number;
}

export interface TablePreviewResponse {
  schema_name: string;
  table_name: string;
  columns: string[];
  rows: unknown[][];
  total_rows: number;
  has_more: boolean;
}

export interface ConnectionListResponse {
  connections: DatabaseConnectionConfig[];
  active_connection_id?: string | null;
}

// Form types for creating/editing connections
export interface ConnectionFormData {
  name: string;
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  ssl_mode: SslMode;
}

export const DEFAULT_CONNECTION_FORM: ConnectionFormData = {
  name: '',
  host: 'localhost',
  port: 5432,
  database: '',
  username: '',
  password: '',
  ssl_mode: 'disable',
};
