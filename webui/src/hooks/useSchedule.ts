import { useState, useEffect, useCallback } from 'react';
import type { ScheduleItem, CreateSchedulePayload } from '../types';
import { apiFetch } from '../lib/api';

export function useSchedule() {
  const [schedules, setSchedules] = useState<ScheduleItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadSchedules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch('/api/schedule');
      if (!resp.ok) throw new Error('Failed to load schedules');
      const data: ScheduleItem[] = await resp.json();
      setSchedules(data || []);
    } catch (e: any) {
      console.error('Failed to load schedules:', e);
      setError(e.message || 'Failed to load schedules');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSchedules();
  }, [loadSchedules]);

  const runSchedule = useCallback(async (id: string | number) => {
    try {
      const resp = await apiFetch(`/api/schedule/${id}/run`, { method: 'POST' });
      if (!resp.ok) {
        const errData = await resp.json();
        return { success: false, error: errData.detail || 'Failed to run schedule' };
      }
      return { success: true };
    } catch (e: any) {
      return { success: false, error: 'Network error: ' + (e.message || 'Unknown error') };
    }
  }, []);

  const deleteSchedule = useCallback(
    async (id: string | number) => {
      try {
        const resp = await apiFetch(`/api/schedule/${id}`, { method: 'DELETE' });
        if (!resp.ok) {
          const errData = await resp.json();
          return { success: false, error: errData.detail || 'Failed to delete schedule' };
        }
        await loadSchedules();
        return { success: true };
      } catch (e: any) {
        return { success: false, error: 'Network error: ' + (e.message || 'Unknown error') };
      }
    },
    [loadSchedules]
  );

  const createSchedule = useCallback(
    async (job: CreateSchedulePayload) => {
      if (!job.name || !job.folder) {
        return { success: false, error: 'Name and folder are required' };
      }

      try {
        const resp = await apiFetch('/api/schedule', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(job),
        });

        if (!resp.ok) {
          const errData = await resp.json();
          return { success: false, error: errData.detail || 'Failed to add schedule' };
        }

        await loadSchedules();
        return { success: true };
      } catch (e: any) {
        return { success: false, error: 'Network error: ' + (e.message || 'Unknown error') };
      }
    },
    [loadSchedules]
  );

  return {
    schedules,
    loading,
    error,
    loadSchedules,
    runSchedule,
    deleteSchedule,
    createSchedule,
  };
}
