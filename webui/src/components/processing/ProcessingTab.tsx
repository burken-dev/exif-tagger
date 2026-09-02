import React, { useState } from 'react';
import { useProcessing } from '@/hooks/useProcessing';
import { useToast } from '@/components/layout/ToastContainer';
import { SessionCard } from './SessionCard';
import { ProgressCard } from './ProgressCard';
import { LogOutputCard } from './LogOutputCard';
import { FolderSelectModal } from '@/components/gallery/FolderSelectModal';

export const ProcessingTab: React.FC = () => {
  const {
    isRunning,
    isPaused,
    rootDirectory,
    folderPath,
    maxImages,
    processedCount,
    totalCount,
    progressPct,
    elapsedSeconds,
    avgSecondsPerImage,
    logs,
    autoScroll,
    statusText,
    summary,
    folders,
    modalFolder,
    folderBreadcrumbs,
    foldersLoading,
    startProcessing,
    pauseProcessing,
    resumeProcessing,
    stopProcessing,
    clearLogs,
    fetchFolders,
    setAutoScroll,
    setFolderPath,
    setMaxImages,
  } = useProcessing();

  const { showToast } = useToast();
  const [isFolderModalOpen, setIsFolderModalOpen] = useState(false);

  const handleBrowseFolders = () => {
    fetchFolders(folderPath);
    setIsFolderModalOpen(true);
  };

  const handleSelectFolder = (path: string) => {
    setFolderPath(path);
    setIsFolderModalOpen(false);
  };

  const handleStart = async () => {
    const res = await startProcessing();
    if (res) {
      if (res.success) {
        showToast('Processing session started', 'success');
      } else if (res.error) {
        showToast(res.error, 'error');
      }
    }
  };

  const handlePause = async () => {
    const res = await pauseProcessing();
    if (res.success) {
      showToast('Processing session paused', 'info');
    } else if (res.error) {
      showToast(res.error, 'error');
    }
  };

  const handleResume = async () => {
    const res = await resumeProcessing();
    if (res.success) {
      showToast('Processing session resumed', 'success');
    } else if (res.error) {
      showToast(res.error, 'error');
    }
  };

  const handleStop = async () => {
    const res = await stopProcessing();
    if (res) {
      if (res.success) {
        showToast('Processing session stop requested', 'info');
      } else if (res.error) {
        showToast(res.error, 'error');
      }
    }
  };

  return (
    <div className="space-y-6">
      <SessionCard
        rootDirectory={rootDirectory}
        folderPath={folderPath}
        onFolderPathChange={setFolderPath}
        onBrowseFolders={handleBrowseFolders}
        maxImages={maxImages}
        onMaxImagesChange={setMaxImages}
        isRunning={isRunning}
        isPaused={isPaused}
        onStart={handleStart}
        onPause={handlePause}
        onResume={handleResume}
        onStop={handleStop}
      />

      <ProgressCard
        processedCount={processedCount}
        totalCount={totalCount}
        progressPct={progressPct}
        statusText={statusText}
        isRunning={isRunning}
        isPaused={isPaused}
        elapsedSeconds={elapsedSeconds}
        avgSecondsPerImage={avgSecondsPerImage}
        summary={summary}
      />

      <LogOutputCard
        logs={logs}
        autoScroll={autoScroll}
        onAutoScrollChange={setAutoScroll}
        onClearLogs={clearLogs}
      />

      {/* Folder Selection Dialog */}
      <FolderSelectModal
        open={isFolderModalOpen}
        onOpenChange={setIsFolderModalOpen}
        currentModalFolder={modalFolder}
        folders={folders}
        breadcrumbs={folderBreadcrumbs}
        onNavigate={(path) => fetchFolders(path)}
        onSelectFolder={handleSelectFolder}
        isFoldersLoading={foldersLoading}
        title="Select Processing Directory"
        description="Navigate and select the directory containing images to process."
      />
    </div>
  );
};

export default ProcessingTab;
