import { useState, useEffect, useCallback, useRef } from 'react';
import type { LogItem, ProcessingStatus, FolderItem, FolderBreadcrumb, FoldersResponse } from '../types';

export function useProcessing() {
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [rootDirectory, setRootDirectory] = useState<string>('');
  const [folderPath, setFolderPathState] = useState<string>(() => {
    try {
      return localStorage.getItem('exif_tagger_processing_folderPath') || '';
    } catch {
      return '';
    }
  });
  const [maxImages, setMaxImagesState] = useState<number | null>(() => {
    try {
      const v = localStorage.getItem('exif_tagger_processing_maxImages');
      return v !== null ? parseInt(v, 10) : null;
    } catch {
      return null;
    }
  });
  const [processedCount, setProcessedCount] = useState<number>(0);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [progressPct, setProgressPct] = useState<number>(0);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [statusText, setStatusText] = useState<string>('Idle');
  const [summary, setSummary] = useState<{ failed: number; errors?: any[] } | null>(null);
  const [folders, setFolders] = useState<FolderItem[]>([]);
  const [modalFolder, setModalFolder] = useState<string>('');
  const [folderBreadcrumbs, setFolderBreadcrumbs] = useState<FolderBreadcrumb[]>([]);
  const [foldersLoading, setFoldersLoading] = useState<boolean>(false);

  const lastProcessedLogIdRef = useRef<number>(0);
  const pollTimerRef = useRef<NodeJS.Timeout | null>(null);
  const wasRunningRef = useRef<boolean>(false);

  // Fetch root_directory from config
  useEffect(() => {
    fetch('/api/config')
      .then((res) => res.json())
      .then((data) => {
        if (data && data.root_directory) {
          setRootDirectory(data.root_directory);
        }
      })
      .catch(() => {});
  }, []);

  const setFolderPath = useCallback((path: string) => {
    try {
      localStorage.setItem('exif_tagger_processing_folderPath', path);
    } catch {}
    setFolderPathState(path);
  }, []);

  const setMaxImages = useCallback((max: number | null) => {
    try {
      if (max === null || isNaN(max)) {
        localStorage.removeItem('exif_tagger_processing_maxImages');
      } else {
        localStorage.setItem('exif_tagger_processing_maxImages', String(max));
      }
    } catch {}
    setMaxImagesState(max);
  }, []);

  // Fetch folder image count preview on folderPath change when not running
  useEffect(() => {
    if (isRunning) return;
    let cancelled = false;
    const url = `/api/gallery/images?limit=1${folderPath ? `&folder=${encodeURIComponent(folderPath)}` : ''}`;
    fetch(url)
      .then((res) => res.json())
      .then((data) => {
        if (!cancelled && typeof data.total === 'number') {
          setTotalCount(data.total);
          setProcessedCount(0);
          setProgressPct(0);
          setSummary(null);
          setStatusText('Idle');
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [folderPath, isRunning]);

  const fetchStatus = useCallback(async () => {
    try {
      const resp = await fetch('/api/status');
      if (!resp.ok) return;
      const data: ProcessingStatus = await resp.json();

      const runningState = Boolean(data.running);
      const prevWasRunning = wasRunningRef.current;
      wasRunningRef.current = runningState;

      if (runningState) {
        setIsRunning(true);
        setStatusText('Running');
        setSummary(data.summary || null);
        setProcessedCount(data.processed || 0);
        setTotalCount(data.total || 0);
        setProgressPct(data.progressPct || 0);
      } else if (data.stopRequested) {
        setIsRunning(false);
        setStatusText('Stopping...');
      } else {
        setIsRunning(false);
        if (prevWasRunning) {
          const hasFailures =
            data.summary && (data.summary.failed > 0 || (data.summary.errors && data.summary.errors.length > 0));
          if (hasFailures) {
            setStatusText('Completed with errors');
          } else if (data.summary) {
            setStatusText('Completed');
          } else {
            setStatusText('Idle');
          }
          setSummary(data.summary || null);
          setProcessedCount(data.processed || 0);
          setTotalCount(data.total || 0);
          setProgressPct(data.progressPct || 0);
        }
      }

      // Append new logs sequentially
      if (data.logs && Array.isArray(data.logs)) {
        const newLogs: LogItem[] = [];
        data.logs.forEach((log) => {
          if (log.id > lastProcessedLogIdRef.current) {
            newLogs.push({
              id: log.id,
              text: log.text,
              type: log.level || log.type || 'info',
            });
            lastProcessedLogIdRef.current = log.id;
          }
        });

        if (newLogs.length > 0) {
          setLogs((prev) => [...prev, ...newLogs]);
        }
      }

      return runningState;
    } catch (e) {
      // silent fail on network glitch during polling
      return false;
    }
  }, []);

  // Polling management
  useEffect(() => {
    let isSubscribed = true;

    const runPoll = async () => {
      const active = await fetchStatus();
      if (!isSubscribed) return;

      const delay = active ? 1000 : 5000;
      pollTimerRef.current = setTimeout(runPoll, delay);
    };

    runPoll();

    return () => {
      isSubscribed = false;
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
      }
    };
  }, [fetchStatus]);

  // Operations
  const startProcessing = useCallback(
    async (overrideFolderPath?: string, overrideMaxImages?: number | null) => {
      const targetFolder = overrideFolderPath !== undefined ? overrideFolderPath : folderPath;
      const targetMax = overrideMaxImages !== undefined ? overrideMaxImages : maxImages;

      try {
        const resp = await fetch('/api/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            rootDirectory: (targetFolder || '').trim() || null,
            maxImages: targetMax || null,
          }),
        });

        if (resp.ok) {
          setLogs([]);
          lastProcessedLogIdRef.current = 0;
          setProcessedCount(0);
          setTotalCount(0);
          setProgressPct(0);
          setSummary(null);
          wasRunningRef.current = true;
          setIsRunning(true);
          setStatusText('Running');
          setLogs([{ id: 0, text: 'Session started.', type: 'info' }]);
          return { success: true };
        } else {
          const errData = await resp.json();
          return { success: false, error: errData.detail || 'Failed to start session' };
        }
      } catch (e: any) {
        return { success: false, error: 'Network error: ' + (e.message || 'Unknown error') };
      }
    },
    [folderPath, maxImages]
  );

  const stopProcessing = useCallback(async () => {
    try {
      const resp = await fetch('/api/stop', { method: 'POST' });
      if (resp.ok) {
        setStatusText('Stopping...');
        setLogs((prev) => [...prev, { id: Date.now(), text: 'Stop requested.', type: 'info' }]);
        return { success: true };
      } else {
        const errData = await resp.json();
        return { success: false, error: errData.detail || 'Failed to stop session' };
      }
    } catch (e: any) {
      return { success: false, error: 'Network error: ' + (e.message || 'Unknown error') };
    }
  }, []);

  const clearLogs = useCallback(() => {
    setLogs([]);
    lastProcessedLogIdRef.current = 0;
  }, []);

  const fetchFolders = useCallback(async (path = '') => {
    setModalFolder(path);
    setFoldersLoading(true);
    try {
      const resp = await fetch(`/api/gallery/folders?path=${encodeURIComponent(path)}`);
      if (!resp.ok) throw new Error('Failed to fetch folders');
      const data: FoldersResponse = await resp.json();
      setFolders(data.folders || []);
      setFolderBreadcrumbs(data.breadcrumbs || []);
    } catch (err: any) {
      console.error('Failed to load folders:', err);
      setFolders([]);
      setFolderBreadcrumbs([]);
    } finally {
      setFoldersLoading(false);
    }
  }, []);

  return {
    isRunning,
    rootDirectory,
    folderPath,
    maxImages,
    processedCount,
    totalCount,
    progressPct,
    logs,
    autoScroll,
    statusText,
    summary,
    folders,
    modalFolder,
    folderBreadcrumbs,
    foldersLoading,
    startProcessing,
    stopProcessing,
    clearLogs,
    fetchFolders,
    setAutoScroll,
    setFolderPath,
    setMaxImages,
  };
}
