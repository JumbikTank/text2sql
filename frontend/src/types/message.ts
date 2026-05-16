export type MessageRole = 'user' | 'assistant';
export type MessageType = 'sql' | 'plain' | 'text_with_csv';

export interface Message {
  role: MessageRole;
  content: string;
  type: MessageType;
  download_link?: string | null;
  sql_query?: string | null;
  preview_data?: string | null;
  id?: string;
  timestamp?: Date;
  lastUpdated?: Date;  // Track when message was last replayed
}

export interface MessagesRequest {
  messages: Message[];
}

export interface ApiError {
  error: string;
  detail?: string;
  status_code?: number;
}
