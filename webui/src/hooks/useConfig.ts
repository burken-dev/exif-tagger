import { useState, useEffect, useCallback } from 'react';
import type { AppConfig } from '../types';
import { apiFetch } from '../lib/api';

export function useConfig() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' | 'info' } | null>(null);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setMessage(null);
    try {
      const resp = await apiFetch('/api/config');
      if (!resp.ok) throw new Error('Failed to fetch config');
      const data: AppConfig = await resp.json();
      setConfig(data);
    } catch (e: any) {
      console.error('Failed to load config:', e);
      setMessage({ text: 'Failed to load configuration', type: 'error' });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const saveConfig = useCallback(async (newConfig: AppConfig) => {
    setSaving(true);
    setMessage(null);
    try {
      const resp = await apiFetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });

      if (resp.ok) {
        setConfig(newConfig);
        setMessage({ text: 'Configuration saved successfully.', type: 'success' });
        return { success: true };
      } else {
        const errData = await resp.json();
        const errorMsg = 'Failed to save config: ' + (errData.detail || 'Unknown error');
        setMessage({ text: errorMsg, type: 'error' });
        return { success: false, error: errorMsg };
      }
    } catch (e: any) {
      const errorMsg = 'Network error: ' + (e.message || 'Unknown error');
      setMessage({ text: errorMsg, type: 'error' });
      return { success: false, error: errorMsg };
    } finally {
      setSaving(false);
    }
  }, []);

  const exportConfig = useCallback(() => {
    if (!config) {
      setMessage({ text: 'No configuration loaded to export', type: 'error' });
      return;
    }
    try {
      const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'exif-tagger-config.json';
      a.click();
      URL.revokeObjectURL(url);
      setMessage({ text: 'Configuration exported successfully.', type: 'success' });
    } catch (e: any) {
      setMessage({ text: 'Export failed: ' + e.message, type: 'error' });
    }
  }, [config]);

  const importConfig = useCallback((importedConfig: AppConfig) => {
    try {
      setConfig(importedConfig);
      setMessage({ text: 'Config imported — click Save to apply', type: 'success' });
    } catch (e: any) {
      setMessage({ text: 'Failed to import config: ' + e.message, type: 'error' });
    }
  }, []);

  return {
    config,
    loading,
    saving,
    message,
    loadConfig,
    saveConfig,
    exportConfig,
    importConfig,
    setConfig,
    setMessage,
  };
}
