import React, { useState } from 'react';
import { Image as ImageIcon, SlidersHorizontal, RefreshCw, Filter, Info } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useGallery } from '@/hooks/useGallery';
import { useToast } from '@/components/layout/ToastContainer';
import { FolderBreadcrumbs } from './FolderBreadcrumbs';
import { FolderSelectModal } from './FolderSelectModal';
import { TagFilterBar } from './TagFilterBar';
import { GalleryToolbar } from './GalleryToolbar';
import { BatchTagPanel } from './BatchTagPanel';
import { GlobalRemoveTagPanel } from './GlobalRemoveTagPanel';
import { ImageGrid } from './ImageGrid';
import { ImageDetailModal } from './ImageDetailModal';
import { PaginationFooter } from './PaginationFooter';

export const GalleryTab: React.FC = () => {
  const {
    images,
    allTags,
    selectedTags,
    selectedImageIds,
    currentFolder,
    searchQuery,
    currentPage,
    pageSize,
    totalImages,
    folders,
    modalFolder,
    folderBreadcrumbs,
    selectedImageDetail,
    isSyncing,
    loading,
    error,
    fetchFolders,
    toggleTagFilter,
    clearTagFilters,
    toggleImageSelection,
    selectAllOnPage,
    deselectAllOnPage,
    applyBatchTags,
    removeTagGlobal,
    updateSingleImageTags,
    fetchImageDetail,
    clearImageDetail,
    syncGalleryIndex,
    syncSingleImage,
    setCurrentFolder,
    setSearchQuery,
    setCurrentPage,
    setPageSize,
  } = useGallery();

  const { showToast } = useToast();
  const [isFolderModalOpen, setIsFolderModalOpen] = useState(false);
  const [showManagementPanels, setShowManagementPanels] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem('gallery.showManagementPanels');
      return stored !== null ? stored === 'true' : true;
    } catch {
      return true;
    }
  });

  const handleToggleManagementPanels = () => {
    setShowManagementPanels(prev => {
      const next = !prev;
      try { localStorage.setItem('gallery.showManagementPanels', String(next)); } catch {}
      return next;
    });
  };

  const hasActiveFilters = Boolean(currentFolder || searchQuery || selectedTags.size > 0);
  const hasNonFolderFilters = Boolean(searchQuery || selectedTags.size > 0);

  const handleOpenFolderModal = () => {
    fetchFolders(currentFolder || '');
    setIsFolderModalOpen(true);
  };

  const handleSyncIndex = async (mode: 'all' | 'filtered' = 'all') => {
    const label = mode === 'filtered' ? 'filtered gallery index' : 'gallery index';
    showToast(`Syncing ${label}...`, 'info');
    const res = await syncGalleryIndex(mode);
    if (res.success) {
      showToast(
        `Gallery sync complete! Total: ${res.stats?.total || 0}, Updated: ${res.stats?.updated || 0}`,
        'success'
      );
    } else {
      showToast(res.error || 'Gallery sync failed', 'error');
    }
  };

  return (
    <div className="space-y-6">
      {/* Main Gallery Container Card */}
      <Card className="border-border">
        <CardHeader className="pb-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <ImageIcon className="w-5 h-5 text-primary" />
                <CardTitle className="text-xl">Image Gallery</CardTitle>
              </div>
              <CardDescription>
                Browse images, filter by tags, and manage EXIF tags across your library.
              </CardDescription>
            </div>

            <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
              <div className="inline-flex rounded-md shadow-sm border border-border bg-card p-0.5">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSyncIndex('all')}
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
                  onClick={() => handleSyncIndex('filtered')}
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

              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleToggleManagementPanels}
                className="flex items-center gap-2 h-9"
              >
                <SlidersHorizontal className="w-4 h-4" />
                <span>{showManagementPanels ? 'Hide Tag Management' : 'Show Tag Management'}</span>
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-5">
          {/* Top Info Banner when totalImages === 0 && !isSyncing && !loading */}
          {totalImages === 0 && !isSyncing && !loading && !hasActiveFilters && (
            <div className="flex items-start gap-3 p-4 rounded-lg border border-indigo-500/30 bg-indigo-500/10 text-indigo-200 text-sm">
              <Info className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold text-indigo-100">No images indexed yet</p>
                <p className="text-xs text-indigo-200/80 mt-0.5">
                  Click <strong>Sync All</strong> or <strong>Sync Filtered</strong> in the top right header to scan your library directory and populate the gallery index.
                </p>
              </div>
            </div>
          )}

          {/* Folder Scope Navigation */}
          <FolderBreadcrumbs
            currentFolder={currentFolder}
            onSelectFolder={setCurrentFolder}
            onOpenModal={handleOpenFolderModal}
          />

          {/* Search Toolbar */}
          <GalleryToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            onSync={handleSyncIndex}
            isSyncing={isSyncing}
            hasActiveFilters={hasActiveFilters}
          />

          {/* Active Tag Filter Badges */}
          <TagFilterBar
            allTags={allTags}
            selectedTags={selectedTags}
            onToggleTag={toggleTagFilter}
            onClearFilters={clearTagFilters}
          />

          {/* Batch Operations & Global Purge Panels */}
          {showManagementPanels && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <BatchTagPanel
                selectedCount={selectedImageIds.size}
                allTags={allTags}
                onApplyBatchTags={applyBatchTags}
              />
              <GlobalRemoveTagPanel
                allTags={allTags}
                onRemoveTagGlobal={removeTagGlobal}
              />
            </div>
          )}

          {/* Error Banner if any */}
          {error && (
            <div className="p-3 rounded-lg border border-destructive/40 bg-destructive/10 text-destructive text-xs">
              <strong>Error:</strong> {error}
            </div>
          )}

          {/* Image Grid with Selection Controls */}
          <ImageGrid
            images={images}
            selectedImageIds={selectedImageIds}
            onToggleSelect={toggleImageSelection}
            onSelectAll={selectAllOnPage}
            onDeselectAll={deselectAllOnPage}
            onImageClick={(img) => fetchImageDetail(img.id !== null ? img.id : img)}
            loading={loading}
            totalImages={totalImages}
            hasActiveFilters={hasActiveFilters}
            hasNonFolderFilters={hasNonFolderFilters}
            onSync={() => handleSyncIndex('all')}
            isSyncing={isSyncing}
            onClearFilters={() => {
              clearTagFilters();
              setCurrentFolder('');
              setSearchQuery('');
            }}
          />

          {/* Pagination Footer */}
          <PaginationFooter
            currentPage={currentPage}
            pageSize={pageSize}
            totalImages={totalImages}
            onPageChange={setCurrentPage}
            onPageSizeChange={setPageSize}
          />
        </CardContent>
      </Card>

      {/* Folder Selection Dialog */}
      <FolderSelectModal
        open={isFolderModalOpen}
        onOpenChange={setIsFolderModalOpen}
        currentModalFolder={modalFolder}
        folders={folders}
        breadcrumbs={folderBreadcrumbs}
        onNavigate={(path) => fetchFolders(path)}
        onSelectFolder={setCurrentFolder}
      />

      {/* Single Image Detail Modal */}
      <ImageDetailModal
        image={selectedImageDetail}
        open={selectedImageDetail !== null}
        onClose={clearImageDetail}
        onUpdateTags={updateSingleImageTags}
        onSyncSingleImage={syncSingleImage}
        allTags={allTags}
      />
    </div>
  );
};

export default GalleryTab;
