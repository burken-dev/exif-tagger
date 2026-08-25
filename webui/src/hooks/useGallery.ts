import { useState, useEffect, useCallback, useRef } from 'react';
import type {
  GalleryImage,
  FolderItem,
  FolderBreadcrumb,
  FoldersResponse,
} from '../types';

export function useGallery() {
  const [images, setImages] = useState<GalleryImage[]>([]);
  const [allTags, setAllTags] = useState<string[]>([]);
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set());
  const [selectedImageIds, setSelectedImageIds] = useState<Set<number>>(new Set());
  const [currentFolder, setCurrentFolder] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(48);
  const [totalImages, setTotalImages] = useState<number>(0);
  const [folders, setFolders] = useState<FolderItem[]>([]);
  const [foldersResponse, setFoldersResponse] = useState<FoldersResponse | null>(null);
  const [modalFolder, setModalFolder] = useState<string>('');
  const [folderBreadcrumbs, setFolderBreadcrumbs] = useState<FolderBreadcrumb[]>([]);
  const [selectedImageDetail, setSelectedImageDetail] = useState<GalleryImage | null>(null);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [foldersLoading, setFoldersLoading] = useState<boolean>(false);
  const [imageDetailLoading, setImageDetailLoading] = useState<boolean>(false);

  const currentFolderRef = useRef<string>(currentFolder);
  const searchQueryRef = useRef<string>(searchQuery);
  const selectedTagsRef = useRef<Set<string>>(selectedTags);
  const currentPageRef = useRef<number>(currentPage);
  const pageSizeRef = useRef<number>(pageSize);
  const isPollingRef = useRef<boolean>(false);
  const isSyncingHashRef = useRef<boolean>(false);
  const galleryAbortController = useRef<AbortController | null>(null);

  useEffect(() => {
    currentFolderRef.current = currentFolder;
  }, [currentFolder]);

  useEffect(() => {
    searchQueryRef.current = searchQuery;
  }, [searchQuery]);

  useEffect(() => {
    selectedTagsRef.current = selectedTags;
  }, [selectedTags]);

  useEffect(() => {
    currentPageRef.current = currentPage;
  }, [currentPage]);

  useEffect(() => {
    pageSizeRef.current = pageSize;
  }, [pageSize]);

  // Parse URL Hash
  const parseUrlHash = useCallback(() => {
    const hash = window.location.hash || '#gallery';
    const [, queryPart] = hash.substring(1).split('?');

    isSyncingHashRef.current = true;

    if (queryPart) {
      const params = new URLSearchParams(queryPart);
      setCurrentFolder(params.get('folder') || '');
      setSearchQuery(params.get('search') || '');

      const tagsParam = params.get('tags');
      const parsedTags = new Set<string>(tagsParam ? tagsParam.split(',').filter(Boolean) : []);
      setSelectedTags(parsedTags);

      const parsedPage = parseInt(params.get('page') || '1', 10);
      setCurrentPage(isNaN(parsedPage) || parsedPage < 1 ? 1 : parsedPage);

      const storedPageSize = parseInt(localStorage.getItem('gallery.pageSize') || '48', 10);
      const parsedLimit = parseInt(params.get('limit') || String(storedPageSize), 10);
      setPageSize(isNaN(parsedLimit) || parsedLimit < 1 ? 48 : parsedLimit);
    } else {
      setCurrentFolder('');
      setSearchQuery('');
      setSelectedTags(new Set());
      setCurrentPage(1);
      const storedPageSizeFallback = parseInt(localStorage.getItem('gallery.pageSize') || '48', 10);
      setPageSize(isNaN(storedPageSizeFallback) || storedPageSizeFallback < 1 ? 48 : storedPageSizeFallback);
    }

    setTimeout(() => {
      isSyncingHashRef.current = false;
    }, 0);
  }, []);

  // Update URL Hash when query parameters change
  const updateUrlHash = useCallback(() => {
    if (isSyncingHashRef.current) return;

    const activeTab = window.location.hash.split('?')[0] || '#gallery';
    const params = new URLSearchParams();

    if (currentFolder) params.set('folder', currentFolder);
    if (searchQuery) params.set('search', searchQuery);
    if (selectedTags.size > 0) params.set('tags', Array.from(selectedTags).join(','));
    if (currentPage > 1) params.set('page', String(currentPage));
    if (pageSize !== 48) params.set('limit', String(pageSize));

    const paramStr = params.toString();
    const newHash = paramStr ? `${activeTab}?${paramStr}` : activeTab;

    if (window.location.hash !== newHash) {
      history.replaceState(null, '', newHash);
    }
  }, [currentFolder, searchQuery, selectedTags, currentPage, pageSize]);

  // Listen to hash change events
  useEffect(() => {
    parseUrlHash();
    window.addEventListener('hashchange', parseUrlHash);
    window.addEventListener('popstate', parseUrlHash);
    return () => {
      window.removeEventListener('hashchange', parseUrlHash);
      window.removeEventListener('popstate', parseUrlHash);
    };
  }, [parseUrlHash]);

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      galleryAbortController.current?.abort();
    };
  }, []);

  // Update URL Hash whenever relevant state changes
  useEffect(() => {
    updateUrlHash();
  }, [updateUrlHash]);

  // Fetch Tags
  const fetchGalleryTags = useCallback(async () => {
    try {
      const resp = await fetch('/api/gallery/tags');
      if (!resp.ok) throw new Error('Failed to fetch gallery tags');
      const data = await resp.json();
      setAllTags(data.tags || []);
    } catch (err: any) {
      console.error('Failed to load gallery tags:', err);
    }
  }, []);

  // Fetch Images
  const fetchGalleryImages = useCallback(async () => {
    galleryAbortController.current?.abort();
    const controller = new AbortController();
    galleryAbortController.current = controller;

    setLoading(true);
    setError(null);
    try {
      const page = currentPageRef.current;
      const size = pageSizeRef.current;
      const tags = selectedTagsRef.current;
      const query = searchQueryRef.current;
      const folder = currentFolderRef.current;

      const offset = (page - 1) * size;
      const tagQuery = Array.from(tags).join(',');
      const trimmedSearch = query.trim();

      let url = `/api/gallery/images?offset=${offset}&limit=${size}`;
      if (tagQuery) url += `&tags=${encodeURIComponent(tagQuery)}`;
      if (trimmedSearch) url += `&search=${encodeURIComponent(trimmedSearch)}`;
      if (folder) url += `&folder=${encodeURIComponent(folder)}`;

      const resp = await fetch(url, { signal: controller.signal });
      if (!resp.ok) throw new Error('Failed to fetch gallery images');
      const data = await resp.json();

      setImages(data.images || []);
      setTotalImages(data.total || 0);

      // Clear or prune selection
      if (!data.total || data.total === 0) {
        setSelectedImageIds(new Set());
      } else if (data.total <= (data.images || []).length) {
        const validIds = new Set(
          (data.images || [])
            .map((img: GalleryImage) => img.id)
            .filter((id: number | null): id is number => id !== null)
        );
        setSelectedImageIds((prev) => {
          if (prev.size === 0) return prev;
          const next = new Set<number>();
          prev.forEach((id) => {
            if (validIds.has(id)) next.add(id);
          });
          return next.size === prev.size ? prev : next;
        });
      }
    } catch (err: any) {
      if (err.name === 'AbortError') return;
      setError(err.message || 'Error loading images');
      setImages([]);
      setTotalImages(0);
      setSelectedImageIds(new Set());
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch Folders for modal / breadcrumbs navigation
  const fetchFolders = useCallback(async (path = '') => {
    setModalFolder(path);
    setFoldersLoading(true);
    try {
      const resp = await fetch(`/api/gallery/folders?path=${encodeURIComponent(path)}`);
      if (!resp.ok) throw new Error('Failed to fetch folders');
      const data: FoldersResponse = await resp.json();
      setFoldersResponse(data);
      setFolders(data.folders || []);
      setFolderBreadcrumbs(data.breadcrumbs || []);
    } catch (err: any) {
      console.error('Failed to load modal folders:', err);
      setFoldersResponse(null);
      setFolders([]);
      setFolderBreadcrumbs([]);
    } finally {
      setFoldersLoading(false);
    }
  }, []);

  // Load tags and images on mount or state change
  useEffect(() => {
    fetchGalleryTags();
  }, [fetchGalleryTags]);

  useEffect(() => {
    fetchGalleryImages();
  }, [fetchGalleryImages, currentFolder, searchQuery, selectedTags, currentPage, pageSize]);

  // Tag filter actions
  const toggleTagFilter = useCallback((tag: string) => {
    setSelectedTags((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) {
        next.delete(tag);
      } else {
        next.add(tag);
      }
      return next;
    });
    setSelectedImageIds(new Set());
    setCurrentPage(1);
  }, []);

  const clearTagFilters = useCallback(() => {
    setSelectedTags(new Set());
    setSelectedImageIds(new Set());
    setSearchQuery('');
    setCurrentPage(1);
  }, []);

  // Selection actions
  const toggleImageSelection = useCallback((id: number | null, checked?: boolean) => {
    if (id === null) return;
    setSelectedImageIds((prev) => {
      const next = new Set(prev);
      const shouldSelect = checked !== undefined ? checked : !next.has(id);
      if (shouldSelect) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
  }, []);

  const selectAllOnPage = useCallback(() => {
    setSelectedImageIds((prev) => {
      const next = new Set(prev);
      images.forEach((img) => {
        if (img.id !== null) {
          next.add(img.id);
        }
      });
      return next;
    });
  }, [images]);

  const deselectAllOnPage = useCallback(() => {
    setSelectedImageIds((prev) => {
      const onPageIds = new Set(images.map((img) => img.id).filter((id): id is number => id !== null));
      const hasOnPageSelected = Array.from(prev).some((id) => onPageIds.has(id));
      if (!hasOnPageSelected) {
        return new Set();
      }
      const next = new Set(prev);
      images.forEach((img) => {
        if (img.id !== null) {
          next.delete(img.id);
        }
      });
      return next;
    });
  }, [images]);

  const clearSelection = useCallback(() => {
    setSelectedImageIds(new Set());
  }, []);

  // Batch operations
  const applyBatchTags = useCallback(
    async (addTags: string[], removeTags: string[]) => {
      const selectedIds = Array.from(selectedImageIds);
      if (selectedIds.length === 0) {
        return { success: false, error: 'No images selected' };
      }
      if (addTags.length === 0 && removeTags.length === 0) {
        return { success: false, error: 'Specify at least one tag to add or remove' };
      }

      try {
        const resp = await fetch('/api/gallery/batch-tags', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            image_ids: selectedIds,
            add_tags: addTags,
            remove_tags: removeTags,
          }),
        });

        if (!resp.ok) {
          const errData = await resp.json();
          return { success: false, error: errData.detail || 'Batch update failed' };
        }

        const data = await resp.json();
        setSelectedImageIds(new Set());
        await fetchGalleryTags();
        await fetchGalleryImages();
        return { success: true, modified: data.modified || 0 };
      } catch (err: any) {
        return { success: false, error: err.message || 'Network error during batch update' };
      }
    },
    [selectedImageIds, fetchGalleryTags, fetchGalleryImages]
  );

  // Global tag removal
  const removeTagGlobal = useCallback(
    async (tagName: string) => {
      const trimmed = tagName.trim().toLowerCase();
      if (!trimmed) {
        return { success: false, error: 'Please enter a tag name to remove globally' };
      }

      try {
        const resp = await fetch('/api/gallery/remove-tag-global', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tag_name: trimmed }),
        });

        if (!resp.ok) {
          const errData = await resp.json();
          return { success: false, error: errData.detail || 'Global removal failed' };
        }

        const data = await resp.json();
        setSelectedImageIds(new Set());
        await fetchGalleryTags();
        await fetchGalleryImages();
        return { success: true, modified: data.modified || 0 };
      } catch (err: any) {
        return { success: false, error: err.message || 'Network error during global tag removal' };
      }
    },
    [fetchGalleryTags, fetchGalleryImages]
  );

  // Update single image tags
  const updateSingleImageTags = useCallback(
    async (imageId: number | null, tags: string[]) => {
      if (imageId === null) {
        return { success: false, error: 'Cannot update tags on unindexed image' };
      }
      try {
        const resp = await fetch(`/api/gallery/image/${imageId}/tags`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tags }),
        });

        if (!resp.ok) {
          const errData = await resp.json();
          return { success: false, error: errData.detail || 'Failed to update tags' };
        }

        await fetchGalleryTags();
        await fetchGalleryImages();
        if (selectedImageDetail && selectedImageDetail.id === imageId) {
          setSelectedImageDetail((prev) => (prev ? { ...prev, tags } : null));
        }
        return { success: true };
      } catch (err: any) {
        return { success: false, error: err.message || 'Network error saving tags' };
      }
    },
    [fetchGalleryTags, fetchGalleryImages, selectedImageDetail]
  );

  // Fetch image detail (for modal)
  const fetchImageDetail = useCallback(async (imageOrId: number | GalleryImage | null) => {
    if (imageOrId === null) {
      setSelectedImageDetail(null);
      setImageDetailLoading(false);
      return;
    }
    if (typeof imageOrId === 'object') {
      setSelectedImageDetail(imageOrId);
      setImageDetailLoading(false);
      return;
    }
    setImageDetailLoading(true);
    try {
      const resp = await fetch(`/api/gallery/image/${imageOrId}`);
      if (!resp.ok) throw new Error('Image not found');
      const data: GalleryImage = await resp.json();
      setSelectedImageDetail(data);
    } catch (err: any) {
      console.error('Failed to fetch image detail:', err);
      setSelectedImageDetail(null);
    } finally {
      setImageDetailLoading(false);
    }
  }, []);

  const clearImageDetail = useCallback(() => {
    setSelectedImageDetail(null);
  }, []);

  // Poll sync status until complete or error
  const pollSyncStatus = useCallback(async () => {
    if (isPollingRef.current) {
      return { success: true };
    }
    isPollingRef.current = true;
    try {
      while (true) {
        await new Promise((resolve) => setTimeout(resolve, 800));
        try {
          const resp = await fetch('/api/gallery/sync/status');
          if (resp.ok) {
            const data = await resp.json();
            if (data.status === 'complete') {
              await fetchGalleryTags();
              await fetchGalleryImages();
              return { success: true, stats: data.stats || { total: 0, updated: 0 } };
            }
            if (data.status === 'error') {
              return { success: false, error: data.error || 'Gallery sync failed' };
            }
          }
        } catch (err: any) {
          console.error('Error polling sync status:', err);
        }
      }
    } finally {
      isPollingRef.current = false;
    }
  }, [fetchGalleryTags, fetchGalleryImages]);

  // Sync Gallery Index
  const syncGalleryIndex = useCallback(
    async (mode?: 'all' | 'filtered') => {
      setIsSyncing(true);
      try {
        const resp = await fetch('/api/gallery/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            mode,
            folder: currentFolderRef.current,
            search: searchQueryRef.current,
            tags: Array.from(selectedTagsRef.current),
          }),
        });
        if (!resp.ok) throw new Error('Sync failed');
        const res = await resp.json();

        if (res.status === 'complete') {
          await fetchGalleryTags();
          await fetchGalleryImages();
          return { success: true, stats: res.stats || { total: 0, updated: 0 } };
        }

        return await pollSyncStatus();
      } catch (err: any) {
        return { success: false, error: err.message || 'Network error during sync' };
      } finally {
        setIsSyncing(false);
      }
    },
    [fetchGalleryTags, fetchGalleryImages, pollSyncStatus]
  );

  // Sync Single Image
  const syncSingleImage = useCallback(
    async (relativePath: string) => {
      try {
        const resp = await fetch('/api/gallery/image/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ relative_path: relativePath }),
        });

        if (!resp.ok) {
          const errData = await resp.json().catch(() => ({}));
          return { success: false, error: errData.detail || 'Failed to sync image' };
        }

        const data: GalleryImage = await resp.json();
        await fetchGalleryTags();
        await fetchGalleryImages();
        if (selectedImageDetail && selectedImageDetail.relative_path === relativePath) {
          setSelectedImageDetail(data);
        }
        return { success: true, image: data };
      } catch (err: any) {
        return { success: false, error: err.message || 'Network error syncing image' };
      }
    },
    [fetchGalleryTags, fetchGalleryImages, selectedImageDetail]
  );

  // Check initial sync status on mount if background sync is already running
  useEffect(() => {
    const checkInitialSyncStatus = async () => {
      try {
        const resp = await fetch('/api/gallery/sync/status');
        if (resp.ok) {
          const data = await resp.json();
          if (data.status === 'running') {
            setIsSyncing(true);
            await pollSyncStatus();
            setIsSyncing(false);
          }
        }
      } catch (err) {
        // ignore initial sync status fetch errors
      }
    };
    checkInitialSyncStatus();
  }, [pollSyncStatus]);


  // Setters with pagination reset when filtering
  const handleSetCurrentFolder = useCallback((folder: string) => {
    setCurrentFolder(folder);
    setSelectedImageIds(new Set());
    setCurrentPage(1);
  }, []);

  const handleSetSearchQuery = useCallback((query: string) => {
    setSearchQuery(query);
    setSelectedImageIds(new Set());
    setCurrentPage(1);
  }, []);

  const handleSetPageSize = useCallback((size: number) => {
    try { localStorage.setItem('gallery.pageSize', String(size)); } catch {}
    setPageSize(size);
  }, []);

  return {
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
    foldersResponse,
    modalFolder,
    folderBreadcrumbs,
    selectedImageDetail,
    isSyncing,
    loading,
    error,
    foldersLoading,
    imageDetailLoading,
    fetchGalleryTags,
    fetchGalleryImages,
    fetchFolders,
    toggleTagFilter,
    clearTagFilters,
    toggleImageSelection,
    selectAllOnPage,
    deselectAllOnPage,
    clearSelection,
    applyBatchTags,
    removeTagGlobal,
    updateSingleImageTags,
    fetchImageDetail,
    clearImageDetail,
    syncGalleryIndex,
    syncSingleImage,
    setCurrentFolder: handleSetCurrentFolder,
    setModalFolder,
    setSearchQuery: handleSetSearchQuery,
    setCurrentPage,
    setPageSize: handleSetPageSize,
  };
}
