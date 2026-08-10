import React, { useState, useEffect } from 'react';
import { Image as ImageIcon, Tag as TagIcon, X, Plus, Save, FileText, RefreshCw, Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useToast } from '@/components/layout/ToastContainer';
import type { GalleryImage } from '@/types';

interface ImageDetailModalProps {
  image: GalleryImage | null;
  open: boolean;
  onClose: () => void;
  onUpdateTags: (imageId: number | null, tags: string[]) => Promise<{ success: boolean; error?: string }>;
  onSyncSingleImage?: (relativePath: string) => Promise<{ success: boolean; image?: GalleryImage; error?: string }>;
  allTags: string[];
  isImageDetailLoading?: boolean;
}

export const ImageDetailModal: React.FC<ImageDetailModalProps> = ({
  image,
  open,
  onClose,
  onUpdateTags,
  onSyncSingleImage,
  allTags,
  isImageDetailLoading = false,
}) => {
  const [tags, setTags] = useState<string[]>([]);
  const [newTagInput, setNewTagInput] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isSyncingSingle, setIsSyncingSingle] = useState(false);
  const { showToast } = useToast();

  useEffect(() => {
    if (image) {
      setTags(image.tags ? [...image.tags] : []);
      setNewTagInput('');
    }
  }, [image]);

  if (!image && !isImageDetailLoading) return null;

  if (isImageDetailLoading && !image) {
    return (
      <Dialog open={open} onOpenChange={(val) => !val && onClose()}>
        <DialogContent className="max-w-4xl w-[95vw] max-h-[90vh] flex flex-col p-0 overflow-hidden bg-background">
          <DialogHeader className="p-4 border-b border-border bg-card/50">
            <DialogTitle className="flex items-center gap-2 text-base font-semibold">
              <ImageIcon className="w-4 h-4 text-primary shrink-0" />
              Loading Image Details...
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 flex items-center justify-center p-8">
            <Loader2 className="w-8 h-8 text-primary animate-spin" />
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  if (!image) return null;

  const handleRemoveTag = (tagToRemove: string) => {
    setTags((prev) => prev.filter((t) => t.toLowerCase() !== tagToRemove.toLowerCase()));
  };

  const handleAddTag = () => {
    const newTags = newTagInput
      .split(',')
      .map((t) => t.trim().toLowerCase())
      .filter((t) => t && !tags.some((existing) => existing.toLowerCase() === t));

    if (newTags.length > 0) {
      setTags((prev) => [...prev, ...newTags]);
      setNewTagInput('');
    }
  };

  const handleSyncImage = async () => {
    if (!image || !onSyncSingleImage) return;
    setIsSyncingSingle(true);
    try {
      const res = await onSyncSingleImage(image.relative_path);
      if (res.success && res.image) {
        showToast('Image synced successfully', 'success');
        setTags(res.image.tags || []);
      } else {
        showToast(res.error || 'Failed to sync image', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Error syncing image', 'error');
    } finally {
      setIsSyncingSingle(false);
    }
  };

  const handleSaveTags = async () => {
    if (!image) return;
    setIsSaving(true);
    try {
      let targetId = image.id;
      if (!image.indexed || targetId === null) {
        if (!onSyncSingleImage) {
          showToast('Single image sync function not provided', 'error');
          setIsSaving(false);
          return;
        }
        const syncRes = await onSyncSingleImage(image.relative_path);
        if (!syncRes.success || !syncRes.image || syncRes.image.id === null) {
          showToast(syncRes.error || 'Failed to auto-index image before saving tags', 'error');
          setIsSaving(false);
          return;
        }
        targetId = syncRes.image.id;
      }

      const result = await onUpdateTags(targetId, tags);
      if (result.success) {
        showToast('Image tags updated successfully', 'success');
      } else {
        showToast(result.error || 'Failed to update tags', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Error updating image tags', 'error');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(val) => !val && onClose()}>
      <DialogContent className="max-w-4xl w-[95vw] max-h-[90vh] flex flex-col p-0 overflow-hidden bg-background">
        <DialogHeader className="p-4 border-b border-border bg-card/50">
          <DialogTitle className="flex items-center gap-2 text-base font-semibold truncate pr-6">
            <ImageIcon className="w-4 h-4 text-primary shrink-0" />
            <span className="truncate">{image.filename}</span>
          </DialogTitle>
          <DialogDescription className="text-xs truncate text-muted-foreground">
            {image.relative_path || image.file_path}
          </DialogDescription>
        </DialogHeader>

        {/* Modal Main Body */}
        <div className="flex-1 grid grid-cols-1 md:grid-cols-3 overflow-y-auto p-4 gap-6">
          {/* Left: Image Preview (2 Columns on MD) */}
          <div className="md:col-span-2 flex flex-col items-center justify-center bg-black/40 rounded-lg p-2 min-h-[300px] border border-border">
            <img
              src={`/api/gallery/image/file?path=${encodeURIComponent(image.relative_path)}`}
              alt={image.filename}
              className="max-h-[60vh] w-auto max-w-full object-contain rounded"
            />
          </div>

          {/* Right: EXIF Metadata & Tag Editor (1 Column on MD) */}
          <div className="flex flex-col space-y-5">
            {/* Tag Management Card */}
            <div className="space-y-3 p-3.5 rounded-lg border border-border bg-card">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <TagIcon className="w-4 h-4 text-primary" />
                  <h3 className="text-sm font-semibold">Image Tags</h3>
                </div>
                <span className="text-xs px-2 py-0.5 rounded bg-muted text-muted-foreground font-mono">
                  {tags.length}
                </span>
              </div>

              {/* Tag Badges List with Remove Button */}
              <div className="flex flex-wrap gap-1.5 min-h-[40px] p-2 rounded bg-background border border-border max-h-36 overflow-y-auto">
                {tags.length > 0 ? (
                  tags.map((t) => (
                    <Badge
                      key={t}
                      variant="secondary"
                      className="text-xs py-0.5 px-2 flex items-center gap-1 bg-secondary text-secondary-foreground"
                    >
                      <span>#{t}</span>
                      <button
                        type="button"
                        onClick={() => handleRemoveTag(t)}
                        className="hover:text-destructive p-0.5 rounded cursor-pointer"
                        aria-label={`Remove tag ${t}`}
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </Badge>
                  ))
                ) : (
                  <span className="text-xs text-muted-foreground italic py-1">
                    No tags applied to this image.
                  </span>
                )}
              </div>

              {/* Add New Tag Field */}
              <div className="flex gap-1.5">
                <Input
                  type="text"
                  list="modal-existing-tags"
                  value={newTagInput}
                  onChange={(e) => setNewTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      handleAddTag();
                    }
                  }}
                  placeholder="Add tag (e.g. portrait)..."
                  className="text-xs h-8"
                />
                <datalist id="modal-existing-tags">
                  {(allTags || []).map((tag) => (
                    <option key={tag} value={tag} />
                  ))}
                </datalist>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={handleAddTag}
                  disabled={!newTagInput.trim()}
                  className="h-8 text-xs shrink-0"
                >
                  <Plus className="w-3.5 h-3.5" />
                </Button>
              </div>

              <Button
                type="button"
                onClick={handleSaveTags}
                disabled={isSaving}
                className="w-full text-xs h-8 gap-1.5 mt-2"
              >
                <Save className="w-3.5 h-3.5" />
                {isSaving ? 'Saving...' : 'Save Tag Changes'}
              </Button>
            </div>

            {/* EXIF Metadata Table/Details */}
            <div className="p-3.5 rounded-lg border border-border bg-card space-y-2.5">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold flex items-center gap-2">
                  <FileText className="w-4 h-4 text-primary" />
                  File & EXIF Info
                </h3>
                {image.indexed ? (
                  <Badge variant="outline" className="bg-emerald-500/10 text-emerald-400 border-emerald-500/30 text-xs">
                    Indexed
                  </Badge>
                ) : (
                  <Badge variant="outline" className="bg-amber-500/10 text-amber-400 border-amber-500/30 text-xs">
                    Unindexed
                  </Badge>
                )}
              </div>

              <div className="space-y-2 text-xs divide-y divide-border/40">
                <div className="flex justify-between pt-1">
                  <span className="text-muted-foreground">ID:</span>
                  <span className="font-mono text-foreground">{image.id ?? 'None (Unindexed)'}</span>
                </div>
                <div className="flex justify-between pt-1">
                  <span className="text-muted-foreground">Filename:</span>
                  <span className="font-mono text-foreground truncate max-w-[180px]" title={image.filename}>
                    {image.filename}
                  </span>
                </div>
                <div className="flex justify-between pt-1">
                  <span className="text-muted-foreground">Path:</span>
                  <span className="font-mono text-foreground truncate max-w-[180px]" title={image.relative_path}>
                    {image.relative_path}
                  </span>
                </div>
                {image.created_at && (
                  <div className="flex justify-between pt-1">
                    <span className="text-muted-foreground">Indexed At:</span>
                    <span className="text-foreground">
                      {new Date(image.created_at).toLocaleString()}
                    </span>
                  </div>
                )}
                {image.updated_at && (
                  <div className="flex justify-between pt-1">
                    <span className="text-muted-foreground">Updated At:</span>
                    <span className="text-foreground">
                      {new Date(image.updated_at).toLocaleString()}
                    </span>
                  </div>
                )}
              </div>

              {onSyncSingleImage && (
                <div className="pt-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleSyncImage}
                    disabled={isSyncingSingle}
                    className="w-full text-xs h-8 gap-1.5 text-amber-400 border-amber-500/40 hover:bg-amber-500/10"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${isSyncingSingle ? 'animate-spin' : ''}`} />
                    <span>{isSyncingSingle ? 'Syncing...' : 'Sync Image & Extract Tags'}</span>
                  </Button>
                </div>
              )}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ImageDetailModal;
