'use client';

import { useState } from 'react';
import { type Install as Item, save as post } from '../lib/api';

// Something this Mac does not have yet (a photo, video or language model; a provider's own tool): one click gets
// it. While it comes, a thin line, a percent and a few plain words; if it stops, why, and "Try again". The work
// itself is a quiet helper on this Mac (settings/install.py), so it goes on if this page is closed.
export function Install({ item, quiet = true }: { item?: Item | null; quiet?: boolean }) {
  const [asked, setAsked] = useState(false);
  const [why, setWhy] = useState('');
  if (!item) return null;
  const start = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setAsked(true);
    setWhy('');
    const saved = await post({ install: item.id });
    if (!saved.ok) {
      setAsked(false);
      setWhy(saved.why || 'That could not be started.');
    }
    window.dispatchEvent(new Event('vs-look')); // the page looks again now, and keeps looking while it installs
  };
  const starting = asked && item.state !== 'running' && item.state !== 'failed' && !why;
  if (item.state === 'running' || starting) {
    const percent = starting ? 0 : item.percent;
    return (
      <span
        className="vs-install"
        data-state="running"
        role="progressbar"
        aria-label={`Installing ${item.name}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        onClick={(e) => e.stopPropagation()}
      >
        <span className="vs-install-words">
          <span>{starting ? 'Starting' : item.words}</span>
          <b>{percent}%</b>
        </span>
        <span className="vs-install-line">
          <i style={{ width: `${Math.max(2, percent)}%` }} />
        </span>
      </span>
    );
  }
  const failed = why || (item.state === 'failed' ? item.error : '');
  return (
    <span className="vs-install" data-state={failed ? 'failed' : 'idle'}>
      {failed && <span className="vs-install-why">{failed}</span>}
      <button
        type="button"
        className="vs-act"
        data-quiet={quiet}
        aria-label={`Install ${item.name}`}
        onClick={start}
      >
        {failed
          ? 'Try again'
          : item.size_gb
            ? `Install · ${item.size_gb} GB`
            : `Install ${item.name}`}
      </button>
    </span>
  );
}
