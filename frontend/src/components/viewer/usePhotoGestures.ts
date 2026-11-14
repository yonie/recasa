import { useCallback, useLayoutEffect, useRef } from "react";

const MAX_SCALE = 5;
const DOUBLE_TAP_SCALE = 2.5;

/**
 * Pinch-to-zoom, pan, double-tap zoom and swipe navigation for the viewer
 * image. Writes transforms directly to the element (no React state per
 * touchmove) so gestures stay at native frame rate. Swipe callbacks only
 * fire when not zoomed in; while zoomed, one finger pans instead.
 */
export function usePhotoGestures({
  resetKey,
  onSwipeLeft,
  onSwipeRight,
}: {
  resetKey: string;
  onSwipeLeft: () => void;
  onSwipeRight: () => void;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const t = useRef({ scale: 1, tx: 0, ty: 0 });
  const pinch = useRef<{ dist: number; mx: number; my: number } | null>(null);
  const pan = useRef<{ x: number; y: number; startX: number; startY: number } | null>(null);
  const swipe = useRef<{ x: number; y: number } | null>(null);
  const lastTap = useRef({ time: 0, x: 0, y: 0 });

  const apply = useCallback((animate: boolean) => {
    const img = imgRef.current;
    if (!img) return;
    img.style.transition = animate
      ? "transform 0.25s ease, opacity 0.2s"
      : "opacity 0.2s";
    const { scale, tx, ty } = t.current;
    img.style.transform =
      scale === 1 && tx === 0 && ty === 0
        ? ""
        : `translate3d(${tx}px, ${ty}px, 0) scale(${scale})`;
  }, []);

  const reset = useCallback(
    (animate: boolean) => {
      t.current = { scale: 1, tx: 0, ty: 0 };
      pinch.current = null;
      pan.current = null;
      apply(animate);
    },
    [apply]
  );

  // New photo: clear any zoom before it paints
  useLayoutEffect(() => {
    reset(false);
  }, [resetKey, reset]);

  // Keep the pan within the scaled image's bounds (image is flex-centered,
  // so its untransformed center coincides with the container center)
  const clampPan = () => {
    const img = imgRef.current;
    const c = containerRef.current;
    if (!img || !c) return;
    const s = t.current.scale;
    const maxTx = Math.max(0, (img.offsetWidth * s - c.clientWidth) / 2);
    const maxTy = Math.max(0, (img.offsetHeight * s - c.clientHeight) / 2);
    t.current.tx = Math.min(maxTx, Math.max(-maxTx, t.current.tx));
    t.current.ty = Math.min(maxTy, Math.max(-maxTy, t.current.ty));
  };

  // Point in container coords relative to its center
  const rel = (clientX: number, clientY: number) => {
    const r = containerRef.current!.getBoundingClientRect();
    return { x: clientX - r.left - r.width / 2, y: clientY - r.top - r.height / 2 };
  };

  const onTouchStart = (e: React.TouchEvent) => {
    if (e.touches.length === 2) {
      const a = e.touches[0]!;
      const b = e.touches[1]!;
      const m = rel((a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2);
      pinch.current = {
        dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY),
        mx: m.x,
        my: m.y,
      };
      pan.current = null;
      swipe.current = null;
    } else if (e.touches.length === 1) {
      const touch = e.touches[0]!;
      if (t.current.scale > 1) {
        pan.current = {
          x: touch.clientX,
          y: touch.clientY,
          startX: touch.clientX,
          startY: touch.clientY,
        };
      } else {
        swipe.current = { x: touch.clientX, y: touch.clientY };
      }
    }
  };

  const onTouchMove = (e: React.TouchEvent) => {
    if (e.touches.length === 2 && pinch.current) {
      const a = e.touches[0]!;
      const b = e.touches[1]!;
      const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      const m = rel((a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2);
      const s0 = t.current.scale;
      const s1 = Math.min(MAX_SCALE, Math.max(1, (s0 * dist) / pinch.current.dist));
      // Keep the content under the pinch midpoint pinned to it
      t.current.tx = m.x - ((pinch.current.mx - t.current.tx) * s1) / s0;
      t.current.ty = m.y - ((pinch.current.my - t.current.ty) * s1) / s0;
      t.current.scale = s1;
      pinch.current = { dist, mx: m.x, my: m.y };
      clampPan();
      apply(false);
    } else if (e.touches.length === 1 && pan.current) {
      const touch = e.touches[0]!;
      t.current.tx += touch.clientX - pan.current.x;
      t.current.ty += touch.clientY - pan.current.y;
      pan.current = { ...pan.current, x: touch.clientX, y: touch.clientY };
      clampPan();
      apply(false);
    }
  };

  // Double-tap toggles zoom at the tapped point
  const handleTap = (clientX: number, clientY: number) => {
    const now = Date.now();
    const prev = lastTap.current;
    const isDoubleTap =
      now - prev.time < 300 && Math.hypot(clientX - prev.x, clientY - prev.y) < 40;
    lastTap.current = { time: isDoubleTap ? 0 : now, x: clientX, y: clientY };
    if (!isDoubleTap) return;
    if (t.current.scale > 1) {
      reset(true);
    } else {
      const m = rel(clientX, clientY);
      t.current = {
        scale: DOUBLE_TAP_SCALE,
        tx: m.x * (1 - DOUBLE_TAP_SCALE),
        ty: m.y * (1 - DOUBLE_TAP_SCALE),
      };
      clampPan();
      apply(true);
    }
  };

  const onTouchEnd = (e: React.TouchEvent) => {
    if (e.touches.length === 1 && pinch.current) {
      // One finger lifted mid-pinch: continue as a pan
      pinch.current = null;
      const touch = e.touches[0]!;
      pan.current =
        t.current.scale > 1
          ? { x: touch.clientX, y: touch.clientY, startX: touch.clientX, startY: touch.clientY }
          : null;
      return;
    }
    if (e.touches.length > 0) return;

    if (pinch.current) {
      pinch.current = null;
      if (t.current.scale < 1.05) reset(true);
      return;
    }
    if (pan.current) {
      const { startX, startY } = pan.current;
      pan.current = null;
      const touch = e.changedTouches[0]!;
      if (Math.hypot(touch.clientX - startX, touch.clientY - startY) < 10) {
        handleTap(touch.clientX, touch.clientY);
      }
      return;
    }
    if (!swipe.current) return;

    const touch = e.changedTouches[0]!;
    const dx = touch.clientX - swipe.current.x;
    const dy = touch.clientY - swipe.current.y;
    swipe.current = null;

    if (Math.abs(dx) < 10 && Math.abs(dy) < 10) {
      handleTap(touch.clientX, touch.clientY);
    } else if (Math.abs(dx) > 50 && Math.abs(dy) < 80) {
      if (dx < 0) onSwipeLeft();
      else onSwipeRight();
    }
  };

  return { imgRef, containerRef, onTouchStart, onTouchMove, onTouchEnd };
}
