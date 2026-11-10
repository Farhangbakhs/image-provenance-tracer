"use client";

import { useId, useRef, useState, type DragEvent } from "react";

/** Drop an image or choose one. Keyboard users reach the same input through the button. */
export function DropZone({
  onFile,
  busy,
  busyLabel = "Uploading…",
  hint,
}: {
  onFile: (file: File) => void;
  busy?: boolean;
  busyLabel?: string;
  hint?: string;
}) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const take = (files: FileList | null) => {
    const file = files?.[0];
    if (file && !busy) onFile(file);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setOver(false);
    take(event.dataTransfer.files);
  };

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      aria-busy={busy}
      className={`flex flex-col items-center justify-center gap-2 border border-dashed px-4 py-10 text-center transition-colors ${
        over ? "border-text bg-surface-2" : "border-line bg-surface-1"
      }`}
    >
      <p className="text-[13px]">{busy ? busyLabel : "Drop an image here"}</p>
      <p className="text-[11px] text-muted">{hint ?? "JPEG, PNG, WebP or GIF, up to 20 MB"}</p>
      <label
        htmlFor={inputId}
        className="mt-2 cursor-pointer border border-line px-3 py-1 text-[12px] hover:border-text focus-within:border-text"
      >
        Choose a file
        <input
          id={inputId}
          ref={input}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          className="sr-only"
          disabled={busy}
          onChange={(event) => {
            take(event.target.files);
            if (input.current) input.current.value = "";
          }}
        />
      </label>
    </div>
  );
}
