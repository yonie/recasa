import L from "leaflet";
import iconRetinaUrl from "leaflet/dist/images/marker-icon-2x.png";
import iconUrl from "leaflet/dist/images/marker-icon.png";
import shadowUrl from "leaflet/dist/images/marker-shadow.png";

// Leaflet guesses its marker image path from its CSS, which breaks once a
// bundler renames the files. Point it at the bundled copies instead (served
// by Recasa itself, so the map works without reaching a CDN).
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({ iconRetinaUrl, iconUrl, shadowUrl });

/** The marker for a location with a single photo. Shared: icons are immutable. */
export const singlePhotoIcon = new L.Icon.Default();

const clusterIcons = new Map<number, L.DivIcon>();

/** Round blue badge with the photo count, cached per count. */
export function clusterIcon(count: number): L.DivIcon {
  let icon = clusterIcons.get(count);
  if (!icon) {
    const size = count > 100 ? 50 : count > 10 ? 40 : 30;
    icon = L.divIcon({
      // Count is a number, so nothing from the API ends up as markup here.
      html: `<div class="cluster-badge cluster-badge-${size}">${count}</div>`,
      className: "custom-cluster-icon",
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    });
    clusterIcons.set(count, icon);
  }
  return icon;
}

/** The red dot marking the Hero Trail's current stop. */
export const activeStopIcon = L.divIcon({
  html: `<div class="active-stop-dot"></div>`,
  className: "active-stop-icon",
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});
