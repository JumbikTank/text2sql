import { useState, useEffect } from 'react';
import { Input, Select } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { ModalFooter } from '@/components/ui/Modal';
import { useConnections } from '@/hooks/useConnection';
import type { DatabaseConnectionConfig, ConnectionFormData, SslMode } from '@/types/schema';
import { DEFAULT_CONNECTION_FORM } from '@/types/schema';
import { CheckCircle, XCircle, Loader2 } from 'lucide-react';

interface ConnectionFormProps {
  initialData?: DatabaseConnectionConfig | null;
  onSuccess: () => void;
  onCancel: () => void;
}

const SSL_OPTIONS = [
  { value: 'disable', label: 'Disable' },
  { value: 'require', label: 'Require' },
  { value: 'verify-ca', label: 'Verify CA' },
  { value: 'verify-full', label: 'Verify Full' },
];

export function ConnectionForm({ initialData, onSuccess, onCancel }: ConnectionFormProps) {
  const [formData, setFormData] = useState<ConnectionFormData>(DEFAULT_CONNECTION_FORM);
  const [errors, setErrors] = useState<Partial<Record<keyof ConnectionFormData, string>>>({});

  const {
    testConnection,
    isTestingConnection,
    testResult,
    saveConnection,
    isSavingConnection,
    updateConnection,
    isUpdatingConnection,
  } = useConnections();

  useEffect(() => {
    if (initialData) {
      setFormData({
        name: initialData.name,
        host: initialData.host,
        port: initialData.port,
        database: initialData.database,
        username: initialData.username,
        password: '', // Don't pre-fill password
        ssl_mode: initialData.ssl_mode,
      });
    } else {
      setFormData(DEFAULT_CONNECTION_FORM);
    }
  }, [initialData]);

  const handleChange = (field: keyof ConnectionFormData, value: string | number) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  const validate = (): boolean => {
    const newErrors: Partial<Record<keyof ConnectionFormData, string>> = {};

    if (!formData.name.trim()) {
      newErrors.name = 'Connection name is required';
    }
    if (!formData.host.trim()) {
      newErrors.host = 'Host is required';
    }
    if (!formData.database.trim()) {
      newErrors.database = 'Database name is required';
    }
    if (!formData.username.trim()) {
      newErrors.username = 'Username is required';
    }
    if (!initialData && !formData.password.trim()) {
      newErrors.password = 'Password is required';
    }
    if (formData.port < 1 || formData.port > 65535) {
      newErrors.port = 'Port must be between 1 and 65535';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleTest = async () => {
    if (!validate()) return;

    const config: DatabaseConnectionConfig = {
      ...formData,
      password: formData.password || (initialData?.password ?? ''),
    };

    await testConnection(config);
  };

  const handleSubmit = async () => {
    if (!validate()) return;

    const config: DatabaseConnectionConfig = {
      ...formData,
      password: formData.password || (initialData?.password ?? ''),
    };

    try {
      if (initialData?.id) {
        await updateConnection(initialData.id, config);
      } else {
        await saveConnection(config);
      }
      onSuccess();
    } catch {
      // Error is handled by the hook
    }
  };

  const isLoading = isTestingConnection || isSavingConnection || isUpdatingConnection;

  return (
    <div className="space-y-4">
      <Input
        label="Connection Name"
        value={formData.name}
        onChange={(e) => handleChange('name', e.target.value)}
        error={errors.name}
        placeholder="My Database"
        disabled={isLoading}
      />

      <div className="grid grid-cols-2 gap-4">
        <Input
          label="Host"
          value={formData.host}
          onChange={(e) => handleChange('host', e.target.value)}
          error={errors.host}
          placeholder="localhost"
          disabled={isLoading}
        />
        <Input
          label="Port"
          type="number"
          value={formData.port}
          onChange={(e) => handleChange('port', parseInt(e.target.value) || 5432)}
          error={errors.port}
          disabled={isLoading}
        />
      </div>

      <Input
        label="Database"
        value={formData.database}
        onChange={(e) => handleChange('database', e.target.value)}
        error={errors.database}
        placeholder="mydb"
        disabled={isLoading}
      />

      <div className="grid grid-cols-2 gap-4">
        <Input
          label="Username"
          value={formData.username}
          onChange={(e) => handleChange('username', e.target.value)}
          error={errors.username}
          placeholder="postgres"
          disabled={isLoading}
        />
        <Input
          label="Password"
          type="password"
          value={formData.password}
          onChange={(e) => handleChange('password', e.target.value)}
          error={errors.password}
          placeholder={initialData ? '(unchanged)' : ''}
          disabled={isLoading}
        />
      </div>

      <Select
        label="SSL Mode"
        value={formData.ssl_mode}
        onChange={(e) => handleChange('ssl_mode', e.target.value as SslMode)}
        options={SSL_OPTIONS}
        disabled={isLoading}
      />

      {testResult && (
        <div
          className={`p-3 rounded-lg flex items-center gap-2 ${
            testResult.if_successful
              ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400'
              : 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400'
          }`}
        >
          {testResult.if_successful ? (
            <CheckCircle className="w-5 h-5" />
          ) : (
            <XCircle className="w-5 h-5" />
          )}
          <div>
            <p className="font-medium">{testResult.message}</p>
            {testResult.server_version && (
              <p className="text-sm opacity-75">
                Server: {testResult.server_version} ({testResult.latency_ms}ms)
              </p>
            )}
          </div>
        </div>
      )}

      <ModalFooter>
        <Button variant="ghost" onClick={onCancel} disabled={isLoading}>
          Cancel
        </Button>
        <Button variant="secondary" onClick={handleTest} disabled={isLoading}>
          {isTestingConnection ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Testing...
            </>
          ) : (
            'Test Connection'
          )}
        </Button>
        <Button onClick={handleSubmit} disabled={isLoading}>
          {isSavingConnection || isUpdatingConnection ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Saving...
            </>
          ) : initialData ? (
            'Update'
          ) : (
            'Save'
          )}
        </Button>
      </ModalFooter>
    </div>
  );
}
