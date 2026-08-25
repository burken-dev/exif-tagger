import React, { useState, useMemo } from 'react';
import { Folder, FolderOpen, ChevronRight, Check, Loader2, Play } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import type { FolderItem, FolderBreadcrumb } from '@/types';

interface FolderSelectModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentModalFolder: string;
  folders: FolderItem[];
  breadcrumbs: FolderBreadcrumb[];
  onNavigate: (path: string) => void;
  onSelectFolder: (path: string) => void;
  onProcessFolder?: (path: string) => void;
  isFoldersLoading?: boolean;
  title?: string;
  description?: string;
}

export const FolderSelectModal: React.FC<FolderSelectModalProps> = ({
  open,
  onOpenChange,
  currentModalFolder,
  folders,
  breadcrumbs,
  onNavigate,
  onSelectFolder,
  onProcessFolder,
  isFoldersLoading = false,
  title = 'Select Image Directory',
  description = 'Navigate directories to filter your gallery photos.',
}) => {
  const [showUnprocessedOnly, setShowUnprocessedOnly] = useState<boolean>(false);

  const handleSelectCurrent = () => {
    onSelectFolder(currentModalFolder);
    onOpenChange(false);
  };

  const displayedFolders = useMemo(() => {
    if (!showUnprocessedOnly) return folders;
    return (folders || []).filter((f) => (f.unprocessed_images ?? 0) > 0);
  }, [folders, showUnprocessedOnly]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl w-full">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FolderOpen className="w-5 h-5 text-primary" />
            {title}
          </DialogTitle>
          <DialogDescription>
            {description}
          </DialogDescription>
        </DialogHeader>

        {/* Modal Breadcrumbs and Filter Controls */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-2.5 rounded-md bg-muted/40 border border-border text-xs">
          <div className="flex flex-wrap items-center gap-1.5 min-w-0">
            {(breadcrumbs || []).map((b, idx) => {
              const isCurrent = b.path === currentModalFolder;
              return (
                <React.Fragment key={b.path || 'root-modal'}>
                  {idx > 0 && <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />}
                  <button
                    type="button"
                    onClick={() => onNavigate(b.path)}
                    className={`inline-flex items-center gap-1 px-2 py-1 rounded transition-colors font-medium cursor-pointer ${
                      isCurrent
                        ? 'bg-primary/20 text-primary font-semibold'
                        : 'text-muted-foreground hover:text-foreground hover:bg-accent'
                    }`}
                  >
                    <span>{b.name || 'Root'}</span>
                    {b.unprocessed_images !== undefined && b.unprocessed_images > 0 && (
                      <span
                        className="w-2 h-2 rounded-full bg-amber-500 inline-block ml-1"
                        title={`${b.unprocessed_images} pending images`}
                      />
                    )}
                  </button>
                </React.Fragment>
              );
            })}
          </div>

          <div className="flex items-center gap-2 shrink-0 self-end sm:self-auto pl-1">
            <label
              htmlFor="modal-unprocessed-only-toggle"
              className="text-xs text-muted-foreground cursor-pointer select-none"
            >
              Only unprocessed
            </label>
            <Switch
              id="modal-unprocessed-only-toggle"
              checked={showUnprocessedOnly}
              onCheckedChange={setShowUnprocessedOnly}
            />
          </div>
        </div>

        {/* Directory Grid */}
        <div className="min-h-[220px] max-h-[350px] overflow-y-auto p-1">
          {isFoldersLoading ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Loader2 className="w-10 h-10 text-primary animate-spin mb-3" />
              <p className="text-sm font-medium text-muted-foreground">Scanning directory...</p>
            </div>
          ) : displayedFolders && displayedFolders.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {displayedFolders.map((f) => {
                const hasPending = (f.unprocessed_images ?? 0) > 0;
                const totalCount = f.total_images ?? f.image_count ?? 0;

                return (
                  <div
                    key={f.relative_path}
                    onClick={() => onNavigate(f.relative_path)}
                    onDoubleClick={() => {
                      onSelectFolder(f.relative_path);
                      onOpenChange(false);
                    }}
                    className="flex items-center justify-between p-3 rounded-lg border border-border bg-card hover:bg-accent/60 hover:border-accent transition-all text-left cursor-pointer group gap-2"
                  >
                    <div className="flex flex-col min-w-0 pr-1 flex-1">
                      <div className="flex items-center gap-2 min-w-0">
                        <Folder
                          className={`w-4 h-4 shrink-0 group-hover:scale-110 transition-transform ${
                            hasPending ? 'text-amber-500' : 'text-primary'
                          }`}
                        />
                        <span className="text-xs font-medium truncate text-foreground" title={f.name}>
                          {f.name}
                        </span>
                      </div>
                      <div className="mt-1">
                        {hasPending ? (
                          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30">
                            {f.unprocessed_images} / {totalCount} pending
                          </span>
                        ) : totalCount > 0 ? (
                          <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                            {totalCount} images
                          </span>
                        ) : (
                          <span className="text-[11px] text-muted-foreground/60 italic">0 images</span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {onProcessFolder && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs text-amber-600 dark:text-amber-400 hover:bg-amber-500/15 transition-colors"
                          onClick={(e) => {
                            e.stopPropagation();
                            onProcessFolder(f.relative_path);
                            onOpenChange(false);
                          }}
                          title={`Process "${f.name}"`}
                        >
                          <Play className="w-3 h-3 mr-1 fill-current" />
                          Process
                        </Button>
                      )}
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs hover:bg-primary hover:text-primary-foreground transition-colors"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectFolder(f.relative_path);
                          onOpenChange(false);
                        }}
                        title={`Select "${f.name}"`}
                      >
                        Select
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-12 text-center text-muted-foreground">
              <Folder className="w-10 h-10 stroke-1 mb-2 opacity-50" />
              <p className="text-sm">
                {showUnprocessedOnly
                  ? 'No folders with unprocessed images found.'
                  : 'No subdirectories found in this folder.'}
              </p>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSelectCurrent} className="gap-1.5">
            <Check className="w-4 h-4" />
            {currentModalFolder
              ? `Select Current Folder ("${currentModalFolder.split('/').pop()}")`
              : 'Select Root Directory'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default FolderSelectModal;
