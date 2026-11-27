'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';

// The last start's verdict on her mind (app/api/token: mind.ts), looked at when the page opens, every half minute and
// when the page is back in view: her mind answering, or a later start that hears her, takes the line away by itself.
const LOOK_AGAIN_MS = 30_000;

function useMindDown(): { down: boolean; phone: boolean } {
  const [seen, setSeen] = useState({ down: false, phone: false });
  useEffect(() => {
    let on = true;
    const look = () =>
      fetch('/api/token', { cache: 'no-store' })
        .then((reply) => (reply.ok ? reply.json() : null))
        .then((said) => {
          if (on && said) setSeen({ down: said.mind === 'down', phone: said.here === 'phone' });
        })
        .catch(() => undefined);
    look();
    const timer = setInterval(
      () => document.visibilityState === 'visible' && look(),
      LOOK_AGAIN_MS
    );
    const back = () => document.visibilityState === 'visible' && look();
    document.addEventListener('visibilitychange', back);
    return () => {
      on = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', back);
    };
  }, []);
  return seen;
}

// The start found her mind cannot answer until something is changed (a clean Mac: the page said nothing of it
// until something was typed): one plain line at the top, its advice a link to Settings at Brain, where another is
// chosen; on a paired phone, where Settings does not open, the same advice for the Mac. Nothing more.
export function MindLine() {
  const { down, phone } = useMindDown();
  if (!down) return null;
  // (on the page's own ground, as the bar below is: a message scrolled under it never shows through its words; above her
  // presence, and clear of the header's corners)
  return (
    <div className="pointer-events-none fixed inset-x-0 top-2 z-[60] flex justify-center px-4 md:top-5">
      <p
        role="alert"
        className="text-muted-foreground bg-background max-w-md rounded-xl px-3 py-1 text-center text-xs leading-4 md:text-sm md:leading-5"
      >
        Viventium&apos;s mind is not answering.{' '}
        {phone ? (
          'On your Mac, choose another Conscious mind in Settings, Brain.'
        ) : (
          <Link
            href="/settings#brain"
            className="text-foreground pointer-events-auto underline-offset-4 hover:underline"
          >
            Choose another Conscious mind in Settings, Brain.
          </Link>
        )}
      </p>
    </div>
  );
}
