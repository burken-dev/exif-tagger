import React from 'react';
import { Folder, FolderOpen, ChevronRight, HardDrive } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { FolderBreadcrumb } from '@/types';

interface FolderBreadcrumbsProps {
  currentFolder: string;
  onSelectFolder: (path: string) => void;
  onOpenModal: () => void;
  breadcrumbs?: FolderBreadcrumb[];
}

export const FolderBreadcrumbs: React.FC<FolderBreadcrumbsProps> = ({
  currentFolder,
  onSelectFolder,
  onOpenModal,
  breadcrumbs: propBreadcrumbs,
}) => {
  const parts = currentFolder ? currentFolder.split('/').filter(Boolean) : [];

  const breadcrumbs: FolderBreadcrumb[] =
    propBreadcrumbs && propBreadcrumbs.length > 0
      ? propBreadcrumbs
      : [
          { name: 'Root', path: '' },
          ...parts.map((part, index) => ({
            name: part,
            path: parts.slice(0, index + 1).join('/'),
          })),
        ];

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg border border-border bg-card/50 text-card-foreground">
      <div className="flex flex-wrap items-center gap-1.5 text-sm overflow-x-auto py-0.5">
        <HardDrive className="w-4 h-4 text-muted-foreground mr-1 shrink-0" />
        {breadcrumbs.map((b, idx) => {
          const isLast = idx === breadcrumbs.length - 1;
          return (
            <React.Fragment key={b.path || 'root'}>
              {idx > 0 && <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />}
              <button
                type="button"
                onClick={() => onSelectFolder(b.path)}
                className={`inline-flex items-center gap-1 px-2 py-1 rounded-md transition-colors text-xs font-medium cursor-pointer ${
                  isLast
                    ? 'bg-primary/10 text-primary font-semibold'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
                }`}
              >
                {idx === 0 ? <FolderOpen className="w-3.5 h-3.5 shrink-0" /> : null}
                <span>{b.name}</span>
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

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onOpenModal}
        className="flex items-center gap-1.5 text-xs shrink-0"
      >
        <Folder className="w-3.5 h-3.5" />
        Browse Folders
      </Button>
    </div>
  );
};

export default FolderBreadcrumbs;
