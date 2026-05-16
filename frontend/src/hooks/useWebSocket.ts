import { useEffect, useRef, useState, useCallback } from 'react';
import {
  useNotificationStore,
  mapNotificationType,
  getNotificationTitle,
} from '@/store/notificationStore';

interface WebSocketMessage {
  type: 'tables_added' | 'tables_removed' | 'scan_complete' | 'scan_error' | 'status';
  connection_id: string;
  tables?: string[];
  message: string;
  timestamp?: string;
  clients?: number;
}

interface UseWebSocketOptions {
  enabled?: boolean;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

interface UseWebSocketReturn {
  isConnected: boolean;
  lastMessage: WebSocketMessage | null;
  sendMessage: (message: string) => void;
  reconnect: () => void;
}

const DEFAULT_RECONNECT_INTERVAL = 3000;
const MAX_RECONNECT_ATTEMPTS = 10;

export function useWebSocket(
  connectionId: string | null,
  options: UseWebSocketOptions = {}
): UseWebSocketReturn {
  const {
    enabled = true,
    reconnectInterval = DEFAULT_RECONNECT_INTERVAL,
    maxReconnectAttempts = MAX_RECONNECT_ATTEMPTS,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectionIdRef = useRef(connectionId);

  const addNotification = useNotificationStore((state) => state.addNotification);

  // Update ref when connectionId changes
  useEffect(() => {
    connectionIdRef.current = connectionId;
  }, [connectionId]);

  const connect = useCallback(() => {
    if (!connectionIdRef.current || !enabled) {
      return;
    }

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    // Build WebSocket URL.
    //
    // In dev, Vite proxies `/ws` to the backend (see vite.config.ts); in prod,
    // the app should be served behind a reverse proxy that forwards the same
    // path. Either way, routing through window.location.host keeps the client
    // working without hardcoded ports.
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${connectionIdRef.current}`;

    console.log(`[WebSocket] Connecting to ${wsUrl}`);

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('[WebSocket] Connected');
        setIsConnected(true);
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = (event) => {
        const raw = typeof event.data === 'string' ? event.data : '';
        if (raw === 'pong' || raw === 'ping') return;

        try {
          const message: WebSocketMessage = JSON.parse(raw);
          console.log('[WebSocket] Message received:', message);
          setLastMessage(message);

          // Handle different message types
          if (message.type !== 'status') {
            addNotification({
              type: mapNotificationType(message.type),
              title: getNotificationTitle(message.type),
              message: message.message,
              tables: message.tables,
              autoDismiss: message.type !== 'scan_error',
            });
          }
        } catch (err) {
          console.error('[WebSocket] Failed to parse message:', err);
        }
      };

      ws.onclose = (event) => {
        console.log(`[WebSocket] Disconnected (code: ${event.code})`);
        setIsConnected(false);
        wsRef.current = null;

        // Attempt to reconnect if not a clean close
        if (
          event.code !== 1000 &&
          reconnectAttemptsRef.current < maxReconnectAttempts &&
          connectionIdRef.current
        ) {
          const backoff = Math.min(
            reconnectInterval * Math.pow(2, reconnectAttemptsRef.current),
            30000
          );
          console.log(
            `[WebSocket] Reconnecting in ${backoff}ms (attempt ${reconnectAttemptsRef.current + 1}/${maxReconnectAttempts})`
          );

          reconnectTimeoutRef.current = setTimeout(() => {
            reconnectAttemptsRef.current++;
            connect();
          }, backoff);
        }
      };

      ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error);
      };
    } catch (err) {
      console.error('[WebSocket] Failed to create connection:', err);
    }
  }, [enabled, reconnectInterval, maxReconnectAttempts, addNotification]);

  const disconnect = useCallback(() => {
    // Clear any pending reconnect
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // Close the connection
    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnect');
      wsRef.current = null;
    }

    setIsConnected(false);
    reconnectAttemptsRef.current = 0;
  }, []);

  const sendMessage = useCallback((message: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(message);
    } else {
      console.warn('[WebSocket] Cannot send message, not connected');
    }
  }, []);

  const reconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    disconnect();
    connect();
  }, [connect, disconnect]);

  // Connect when connectionId changes or component mounts
  useEffect(() => {
    if (connectionId && enabled) {
      connect();
    } else {
      disconnect();
    }

    return () => {
      disconnect();
    };
  }, [connectionId, enabled, connect, disconnect]);

  // Send periodic ping to keep connection alive
  useEffect(() => {
    if (!isConnected) return;

    const pingInterval = setInterval(() => {
      sendMessage('ping');
    }, 30000);

    return () => {
      clearInterval(pingInterval);
    };
  }, [isConnected, sendMessage]);

  return {
    isConnected,
    lastMessage,
    sendMessage,
    reconnect,
  };
}
