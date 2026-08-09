import React from 'react';
import { CheckSquare, Square, Tag as TagIcon } from 'lucide-react';
import type { GalleryImage } from '@/types';

interface ImageCardProps {
  image: GalleryImage;
  isSelected: boolean;
  onToggleSelect: (id: number | null, checked?: boolean) => void;
  onClick: (image: GalleryImage) => void;
}

export const ImageCard: React.FC<ImageCardProps> = ({
  image,
  isSelected,
  onToggleSelect,
  onClick,
}) => {
  return (
    <div
      className={`group relative rounded-lg overflow-hidden border border-border bg-card transition-all duration-200 shadow-sm hover:shadow-md ${
        isSelected
          ? 'ring-2 ring-primary border-primary'
          : 'hover:ring-2 hover:ring-primary/40 hover:border-primary/50'
      }`}
    >
      {/* Checkbox Overlay (Top Left) */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onToggleSelect(image.id);
        }}
        disabled={image.id === null}
        className={`absolute top-2 left-2 z-20 p-1 rounded-md transition-all cursor-pointer ${
          isSelected
            ? 'bg-primary text-primary-foreground opacity-100 shadow-sm'
            : image.id === null
            ? 'bg-black/40 text-white/40 opacity-0 group-hover:opacity-60 cursor-not-allowed'
            : 'bg-black/60 text-white/80 opacity-0 group-hover:opacity-100 hover:bg-black/80 hover:text-white'
        }`}
        title={image.id === null ? 'Cannot select unindexed image' : isSelected ? 'Deselect image' : 'Select image'}
      >
        {isSelected ? (
          <CheckSquare className="w-4 h-4" />
        ) : (
          <Square className="w-4 h-4" />
        )}
      </button>

      {/* Unindexed Overlay Badge (Top Right) */}
      {!image.indexed && (
        <span className="absolute top-2 right-2 z-20 text-[10px] font-semibold bg-amber-500/90 text-amber-950 px-1.5 py-0.5 rounded shadow-sm flex items-center gap-1">
          ⚠️ Unindexed
        </span>
      )}

      {/* Thumbnail Aspect Square Box */}
      <div
        onClick={() => onClick(image)}
        className="aspect-square relative w-full overflow-hidden bg-muted cursor-pointer"
      >
        <img
          src={
            image.id !== null
              ? `/api/gallery/image/${image.id}/file`
              : `/api/gallery/image/file?path=${encodeURIComponent(image.relative_path)}`
          }
          alt={image.filename}
          loading="lazy"
          className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
        />

        {/* Thumbnail Hover Gradient Overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex flex-col justify-end p-2.5 z-10 pointer-events-none">
          <p className="text-xs font-semibold text-white truncate" title={image.filename}>
            {image.filename}
          </p>
          <p className="text-[10px] text-slate-300 truncate" title={image.relative_path}>
            {image.relative_path}
          </p>
          
          {/* Hover Tag Badges */}
          <div className="flex flex-wrap gap-1 mt-1.5 max-h-12 overflow-hidden">
            {!image.indexed ? (
              <span className="text-[10px] text-amber-300 font-medium italic">Unprocessed</span>
            ) : image.tags && image.tags.length > 0 ? (
              image.tags.map((t) => (
                <span
                  key={t}
                  className="text-[9px] font-medium bg-primary/80 text-primary-foreground px-1.5 py-0.2 rounded-full"
                >
                  #{t}
                </span>
              ))
            ) : (
              <span className="text-[10px] text-slate-400 italic">No tags</span>
            )}
          </div>
        </div>
      </div>

      {/* Visible Bottom Card Details */}
      <div className="p-2 border-t border-border/40 bg-card/80">
        <p className="text-xs font-medium truncate text-foreground" title={image.filename}>
          {image.filename}
        </p>
        <div className="flex items-center gap-1 mt-1 overflow-x-auto text-[10px] text-muted-foreground py-0.5">
          {!image.indexed ? (
            <span className="text-amber-500 font-medium bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">
              Unprocessed
            </span>
          ) : image.tags && image.tags.length > 0 ? (
            <div className="flex items-center gap-1 truncate">
              <TagIcon className="w-3 h-3 text-primary shrink-0" />
              <span className="truncate">{image.tags.map((t) => `#${t}`).join(', ')}</span>
            </div>
          ) : (
            <span className="text-muted-foreground/60 italic">Untagged</span>
          )}
        </div>
      </div>
    </div>
  );
};

export default ImageCard;
