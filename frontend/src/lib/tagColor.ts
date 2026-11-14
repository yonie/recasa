export interface TagColor {
  bg: string;
  bgHover: string;
  text: string;
}

/**
 * Deterministic string-to-color: hashes the tag name to pick a hue, then
 * returns a light background / dark text pair suitable for pills. The same
 * tag gets the same color on the tags page and in the viewer.
 */
export function getTagColor(name: string): TagColor {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash + name.charCodeAt(i)) | 0;
  }
  const hue = ((hash % 360) + 360) % 360;
  return {
    bg: `hsl(${hue}, 55%, 93%)`,
    bgHover: `hsl(${hue}, 55%, 87%)`,
    text: `hsl(${hue}, 60%, 32%)`,
  };
}
