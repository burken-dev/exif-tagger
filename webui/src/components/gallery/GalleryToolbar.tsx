import React from 'react';
import { Search, X, RefreshCw, Filter } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

interface GalleryToolbarProps {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  onSync?: (mode?: 'all' | 'filtered') => void;
  isSyncing?: boolean;
  hasActiveFilters?: boolean;
}

export const GalleryToolbar: React.FC<GalleryToolbarProps> = ({
  searchQuery,
  onSearchChange,
  onSync,
  isSyncing = false,
  hasActiveFilters = false,
}) => {
  return (
    <div className="flex flex-col sm:flex-row items-center gap-3">
      {/* Search Input */}
      <div className="relative flex-1 w-full">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
        <Input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search images by filename or pattern..."
          className="pl-9 pr-9 text-sm w-full"
        />
        {searchQuery && (
          <button
            type="button"
            onClick={() => onSearchChange('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground p-0.5 rounded cursor-pointer"
            aria-label="Clear search"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Dual Sync Controls */}
      {onSync && (
        <div className="flex items-center gap-1.5 shrink-0 w-full sm:w-auto justify-end">
          <div className="inline-flex rounded-md shadow-sm border border-border bg-card p-0.5">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onSync('all')}
              disabled={isSyncing}
              className="h-8 text-xs px-2.5 gap-1.5 rounded-r-none font-medium hover:bg-muted"
              title="Sync all images in library"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isSyncing ? 'animate-spin text-primary' : ''}`} />
              <span>Sync All</span>
            </Button>
            <div className="w-[1px] bg-border my-1" />
            <Button
              type="button"
              variant={hasActiveFilters ? 'default' : 'ghost'}
              size="sm"
              onClick={() => onSync('filtered')}
              disabled={isSyncing}
              className={`h-8 text-xs px-2.5 gap-1.5 rounded-l-none font-medium ${
                hasActiveFilters
                  ? 'bg-amber-500 hover:bg-amber-600 text-amber-950 font-semibold shadow-sm'
                  : 'text-muted-foreground hover:bg-muted'
              }`}
              title={
                hasActiveFilters
                  ? 'Sync images matching current folder, search query, or tag filters'
                  : 'Sync filtered images'
              }
            >
              <Filter className="w-3.5 h-3.5" />
              <span>Sync Filtered</span>
              {hasActiveFilters && (
                <span className="w-1.5 h-1.5 rounded-full bg-amber-950 animate-pulse" />
              )}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

export default GalleryToolbar;
