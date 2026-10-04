/** Downscale an image file to a small JPEG data URL for previews (null for non-images). */
export async function thumbnail(file: File, max = 480): Promise<string | null> {
  if (!file.type.startsWith("image/")) return null;
  try {
    const img = await createImageBitmap(file);
    const scale = Math.min(1, max / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.7);
  } catch {
    return null;
  }
}

export const typeFromMime = (mime: string) =>
  mime.startsWith("image/") ? "photo" : mime === "message/rfc822" || mime.startsWith("text/") ? "message" : "document";

/** Local datetime string for <input type="datetime-local">. */
export const localDateTime = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
