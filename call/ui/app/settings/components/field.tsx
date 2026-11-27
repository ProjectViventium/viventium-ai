'use client';

import { useEffect, useState } from 'react';
import { MeshGradient } from '@paper-design/shaders-react';

// The living field behind the glass: a slow, quiet current in the page's own colours, drawn on the GPU
// (@paper-design/shaders, 8 kB). It pauses itself when the tab is hidden; it holds still when you ask
// for reduced motion; and without WebGL the page's plain background is what you see.
function colours(): string[] {
  const style = getComputedStyle(document.querySelector('.vs') ?? document.documentElement);
  return [1, 2, 3, 4].map((n) => style.getPropertyValue(`--field-${n}`).trim() || '#111214');
}

export function Field() {
  const [palette, setPalette] = useState<string[] | null>(null);
  const [still, setStill] = useState(false);
  useEffect(() => {
    const read = () => setPalette(colours());
    read();
    const theme = new MutationObserver(read); // light and dark each have their own four colours
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const move = () => setStill(motion.matches);
    move();
    motion.addEventListener('change', move);
    return () => {
      theme.disconnect();
      motion.removeEventListener('change', move);
    };
  }, []);
  return (
    <div className="vs-field" aria-hidden="true">
      {palette && (
        <MeshGradient
          colors={palette}
          distortion={0.9}
          swirl={0.35}
          grainOverlay={0.06}
          speed={still ? 0 : 0.18}
          minPixelRatio={1}
          maxPixelCount={1_400_000}
        />
      )}
    </div>
  );
}
