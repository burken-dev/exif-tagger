import React from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Folder, FolderOpen, Play, Pause, Square, Hash } from 'lucide-react';

export interface SessionCardProps {
  rootDirectory?: string;
  folderPath: string;
  onFolderPathChange: (path: string) => void;
  onBrowseFolders: () => void;
  maxImages: number | null;
  onMaxImagesChange: (max: number | null) => void;
  isRunning: boolean;
  isPaused: boolean;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
}

export const SessionCard: React.FC<SessionCardProps> = ({
  rootDirectory,
  folderPath,
  onFolderPathChange,
  onBrowseFolders,
  maxImages,
  onMaxImagesChange,
  isRunning,
  isPaused,
  onStart,
  onPause,
  onResume,
  onStop,
}) => {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!isRunning) {
      onStart();
    } else if (isPaused) {
      onResume();
    } else {
      onPause();
    }
  };

  const handleFolderPathChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    let val = e.target.value;
    if (rootDirectory && val.startsWith(rootDirectory)) {
      val = val.substring(rootDirectory.length).replace(/^[\/\\]+/, '');
    }
    onFolderPathChange(val);
  };

  const handleMaxImagesChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    if (val === '') {
      onMaxImagesChange(null);
    } else {
      const num = parseInt(val, 10);
      onMaxImagesChange(isNaN(num) ? null : Math.max(1, num));
    }
  };

  const displayRootPrefix = rootDirectory
    ? `${rootDirectory.replace(/[\/\\]+$/, '')}/`
    : '';

  return (
    <Card className="border-border shadow-sm">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Folder className="w-5 h-5 text-primary" />
          <CardTitle>Session Control</CardTitle>
        </div>
        <CardDescription>
          Configure target directory path and maximum image processing limits.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label htmlFor="folderPath" className="text-sm font-medium text-foreground flex items-center gap-1.5">
                <Folder className="w-4 h-4 text-muted-foreground" />
                Folder Path
              </label>
              <div className="flex gap-2">
                <div className="flex flex-1 items-center rounded-md border border-input bg-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 overflow-hidden">
                  {displayRootPrefix && (
                    <span className="px-2.5 py-1.5 text-xs font-mono text-muted-foreground bg-muted border-r border-border shrink-0 select-none">
                      {displayRootPrefix}
                    </span>
                  )}
                  <Input
                    id="folderPath"
                    type="text"
                    value={folderPath}
                    onChange={handleFolderPathChange}
                    placeholder="subfolder (leave empty for root)"
                    disabled={isRunning}
                    className="flex-1 border-0 focus-visible:ring-0 focus-visible:ring-offset-0 rounded-none"
                  />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={onBrowseFolders}
                  disabled={isRunning}
                  className="flex items-center gap-1.5 shrink-0 h-9"
                >
                  <FolderOpen className="w-4 h-4" />
                  Browse
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Subdirectory relative to gallery root to process.
              </p>
            </div>

            <div className="space-y-2">
              <label htmlFor="maxImages" className="text-sm font-medium text-foreground flex items-center gap-1.5">
                <Hash className="w-4 h-4 text-muted-foreground" />
                Max Images
              </label>
              <Input
                id="maxImages"
                type="number"
                min={1}
                value={maxImages === null ? '' : maxImages}
                onChange={handleMaxImagesChange}
                placeholder="Optional limit (e.g. 100)"
                disabled={isRunning}
              />
              <p className="text-xs text-muted-foreground">
                Leave empty to process all images in directory.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 pt-2">
            {!isRunning ? (
              <Button
                type="submit"
                variant="default"
                className="flex items-center gap-2"
              >
                <Play className="w-4 h-4" />
                Start Processing
              </Button>
            ) : isPaused ? (
              <Button
                type="button"
                variant="default"
                onClick={onResume}
                className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white"
              >
                <Play className="w-4 h-4" />
                Resume Processing
              </Button>
            ) : (
              <Button
                type="button"
                variant="secondary"
                onClick={onPause}
                className="flex items-center gap-2 border border-amber-500/40 text-amber-500 hover:bg-amber-500/10"
              >
                <Pause className="w-4 h-4" />
                Pause Processing
              </Button>
            )}

            <Button
              type="button"
              variant="destructive"
              disabled={!isRunning}
              onClick={onStop}
              className="flex items-center gap-2"
            >
              <Square className="w-4 h-4" />
              Stop Processing
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
};

export default SessionCard;
