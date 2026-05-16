import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Button } from './ui/Button';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[ErrorBoundary] caught error:', error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ error: null });
  };

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-gray-50 dark:bg-gray-950">
        <div className="max-w-lg w-full bg-white dark:bg-gray-900 rounded-lg border border-red-200 dark:border-red-900 shadow-lg p-6">
          <div className="flex items-start gap-3 mb-4">
            <AlertTriangle className="w-6 h-6 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                Something went wrong
              </h1>
              <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                The UI hit an unexpected error. Your data is safe.
              </p>
            </div>
          </div>

          {this.state.error.message && (
            <pre className="text-xs bg-gray-100 dark:bg-gray-800 p-3 rounded overflow-x-auto mb-4 text-red-700 dark:text-red-300">
              {this.state.error.message}
            </pre>
          )}

          <div className="flex gap-2">
            <Button onClick={this.handleReset} variant="secondary" size="sm" className="gap-2">
              Try again
            </Button>
            <Button onClick={this.handleReload} size="sm" className="gap-2">
              <RefreshCw className="w-4 h-4" />
              Reload page
            </Button>
          </div>
        </div>
      </div>
    );
  }
}
