import { create } from 'zustand';

export type NotificationType = 'info' | 'success' | 'warning' | 'error';

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  tables?: string[];
  timestamp: Date;
  autoDismiss?: boolean;
}

interface NotificationState {
  notifications: Notification[];

  // Actions
  addNotification: (
    notification: Omit<Notification, 'id' | 'timestamp'>
  ) => string;
  dismissNotification: (id: string) => void;
  clearAll: () => void;
}

let notificationId = 0;

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],

  addNotification: (notification) => {
    const id = `notification-${++notificationId}`;
    const newNotification: Notification = {
      ...notification,
      id,
      timestamp: new Date(),
      autoDismiss: notification.autoDismiss ?? true,
    };

    set((state) => ({
      notifications: [...state.notifications, newNotification],
    }));

    // Auto-dismiss after 5 seconds if autoDismiss is true
    if (newNotification.autoDismiss) {
      setTimeout(() => {
        set((state) => ({
          notifications: state.notifications.filter((n) => n.id !== id),
        }));
      }, 5000);
    }

    return id;
  },

  dismissNotification: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    })),

  clearAll: () => set({ notifications: [] }),
}));

// Helper function to map WebSocket notification types to UI notification types
export function mapNotificationType(
  wsType: string
): NotificationType {
  switch (wsType) {
    case 'tables_added':
      return 'success';
    case 'tables_removed':
      return 'warning';
    case 'scan_complete':
      return 'info';
    case 'scan_error':
      return 'error';
    default:
      return 'info';
  }
}

// Helper function to get notification title from WebSocket type
export function getNotificationTitle(wsType: string): string {
  switch (wsType) {
    case 'tables_added':
      return 'New Tables Detected';
    case 'tables_removed':
      return 'Tables Removed';
    case 'scan_complete':
      return 'Scan Complete';
    case 'scan_error':
      return 'Scan Error';
    default:
      return 'Notification';
  }
}
