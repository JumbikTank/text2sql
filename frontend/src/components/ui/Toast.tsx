import { X, CheckCircle, AlertTriangle, Info, XCircle, Table } from 'lucide-react';
import type { Notification, NotificationType } from '@/store/notificationStore';

interface ToastProps {
  notification: Notification;
  onDismiss: (id: string) => void;
}

const iconMap: Record<NotificationType, React.ComponentType<{ className?: string }>> = {
  success: CheckCircle,
  warning: AlertTriangle,
  info: Info,
  error: XCircle,
};

const colorMap: Record<NotificationType, string> = {
  success: 'bg-green-50 border-green-200 dark:bg-green-900/20 dark:border-green-800',
  warning: 'bg-amber-50 border-amber-200 dark:bg-amber-900/20 dark:border-amber-800',
  info: 'bg-blue-50 border-blue-200 dark:bg-blue-900/20 dark:border-blue-800',
  error: 'bg-red-50 border-red-200 dark:bg-red-900/20 dark:border-red-800',
};

const iconColorMap: Record<NotificationType, string> = {
  success: 'text-green-500',
  warning: 'text-amber-500',
  info: 'text-blue-500',
  error: 'text-red-500',
};

export function Toast({ notification, onDismiss }: ToastProps) {
  const Icon = iconMap[notification.type];
  const colorClass = colorMap[notification.type];
  const iconColor = iconColorMap[notification.type];

  return (
    <div
      className={`
        relative flex items-start gap-3 p-4 rounded-lg border shadow-lg
        animate-in slide-in-from-right-full duration-300
        ${colorClass}
      `}
      role="alert"
    >
      <Icon className={`w-5 h-5 flex-shrink-0 ${iconColor}`} />

      <div className="flex-1 min-w-0">
        <h4 className="font-medium text-gray-900 dark:text-gray-100">
          {notification.title}
        </h4>
        <p className="text-sm text-gray-600 dark:text-gray-300 mt-1">
          {notification.message}
        </p>

        {notification.tables && notification.tables.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {notification.tables.slice(0, 5).map((table) => (
              <span
                key={table}
                className="inline-flex items-center gap-1 px-2 py-0.5 text-xs
                  bg-white/50 dark:bg-gray-800/50 rounded border
                  border-gray-200 dark:border-gray-700
                  text-gray-700 dark:text-gray-300"
              >
                <Table className="w-3 h-3" />
                {table}
              </span>
            ))}
            {notification.tables.length > 5 && (
              <span className="text-xs text-gray-500 dark:text-gray-400 px-1">
                +{notification.tables.length - 5} more
              </span>
            )}
          </div>
        )}
      </div>

      <button
        onClick={() => onDismiss(notification.id)}
        className="flex-shrink-0 p-1 rounded hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
        aria-label="Dismiss notification"
      >
        <X className="w-4 h-4 text-gray-500" />
      </button>
    </div>
  );
}
