/** Trigger one browser download and release the temporary object URL afterwards. */
export function downloadBlob(blob: Blob, filename: string): void {
  const objectURL = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectURL;
  anchor.download = filename.replace(/[\/\\:\u0000-\u001f]/g, "-").trim() || "download";
  document.body.append(anchor); anchor.click(); anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectURL), 1000);
}
