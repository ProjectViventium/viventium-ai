'use client';

import { useEffect, useMemo } from 'react';
import { FileIcon, X } from 'lucide-react';
import { cn } from '@/lib/shadcn/utils';

/** The chat's file limit, both ways (core/attachments.py MAX_BYTES). */
export const MAX_FILE_BYTES = 49_000_000;

export function fileSize(bytes: number): string {
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
  return `${bytes} bytes`;
}

// A picture shown as a small picture; never an SVG (an image tag would not run its scripts, but nothing here needs one).
const PICTURE = /^image\/(png|jpe?g|gif|webp|bmp|avif)$/;

/** A file in a message: the file itself (sent now), or what the conversation's record keeps of one sent earlier. */
export type SentFile = File | { name: string; size: number; type: string };

function Thumb({ file }: { file: File }) {
  const url = useMemo(() => URL.createObjectURL(file), [file]);
  useEffect(() => () => URL.revokeObjectURL(url), [url]);
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt={file.name} className="size-16 rounded-md object-cover" />;
}

/**
 * Files in a message: a small picture for a photo, else its name and size. With `onRemove`, a draft's files, each
 * with its own remove button and one to remove them all.
 */
export function AttachedFiles({
  files,
  onRemove,
  onClear,
  className,
}: {
  files: SentFile[];
  onRemove?: (index: number) => void;
  onClear?: () => void;
  className?: string;
}) {
  if (!files.length) return null;
  return (
    <div
      className={cn('flex flex-wrap items-center gap-1.5', className)}
      aria-label={onRemove ? 'Files to send' : 'Files sent'}
    >
      {files.map((file, index) => (
        <span
          key={`${file.name}-${file.size}-${index}`}
          className="bg-foreground/5 flex max-w-60 items-center gap-1.5 rounded-xl p-1 pr-2 text-xs"
        >
          {file instanceof File && PICTURE.test(file.type) ? (
            <Thumb file={file} />
          ) : (
            <FileIcon className="text-muted-foreground ml-1 size-4 shrink-0" aria-hidden />
          )}
          <span className="min-w-0">
            <span className="block truncate" title={file.name}>
              {file.name}
            </span>
            <span className="text-muted-foreground block">{fileSize(file.size)}</span>
          </span>
          {onRemove && (
            <button
              type="button"
              aria-label={`Remove ${file.name}`}
              title="Remove"
              onClick={() => onRemove(index)}
              className="hover:bg-foreground/10 ml-auto shrink-0 rounded-full p-1"
            >
              <X className="size-3" />
            </button>
          )}
        </span>
      ))}
      {onClear && files.length > 1 && (
        <button
          type="button"
          onClick={onClear}
          className="text-muted-foreground hover:text-foreground px-1 text-xs"
        >
          Remove all
        </button>
      )}
    </div>
  );
}
