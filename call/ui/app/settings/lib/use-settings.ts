'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { type Change, type Settings, save as post, show } from './api';

// The settings, live. A change shows at once (what you chose), is saved by itself, and is put back with a plain
// reason if this Mac cannot run it. While a change is being applied, or something is being installed, the page
// looks again every two seconds.
export function useSettings() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(0);
  const [saved, setSaved] = useState(0); // counts the changes that were kept, so the page can say so
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const pending = useRef(0);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const say = useCallback((text: string) => {
    setNotice(text);
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    if (text) noticeTimer.current = setTimeout(() => setNotice(''), 7000);
  }, []);

  const refresh = useCallback(async () => {
    if (pending.current) return; // never paint an older answer over a choice still being saved
    try {
      const fresh = await show();
      if (!pending.current) setSettings(fresh);
    } catch {
      setSettings((had) => {
        if (!had) say('The settings could not be read. Is Viventium running?');
        return had;
      });
    }
  }, [say]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const busy = settings
    ? (settings.applying.state !== 'idle' && settings.applying.state !== 'failed') ||
      settings.installing ||
      settings.accounts.some(
        (a) =>
          a.plan?.accounts?.some((added) => added.status === 'connecting') ||
          !!a.mind?.setup ||
          a.mind?.pending
      ) // (a sign-in runs)
    : false;
  useEffect(() => {
    window.addEventListener('vs-look', refresh); // an install was just started (components/install.tsx)
    return () => window.removeEventListener('vs-look', refresh);
  }, [refresh]);
  useEffect(() => {
    const timer = setInterval(refresh, busy ? 2000 : 8000);
    return () => clearInterval(timer);
  }, [busy, refresh]);

  // One change at a time, in the order you made them. `now` paints your choice before the answer comes.
  const save = useCallback(
    (change: Change, now?: (s: Settings) => Settings) => {
      pending.current += 1;
      setSaving((n) => n + 1);
      if (now) setSettings((had) => (had ? now(had) : had));
      const run = queue.current.then(async () => {
        const saved = await post(change);
        pending.current -= 1;
        setSaving((n) => n - 1);
        if (saved.ok && saved.state) {
          if (!pending.current) setSettings(saved.state);
          setSaved((n) => n + 1);
          return true;
        }
        say(saved.why || 'That could not be saved.');
        if (!pending.current) {
          try {
            setSettings(await show());
          } catch {
            /* the next look will bring it */
          }
        }
        return false;
      });
      queue.current = run.catch(() => undefined);
      return run;
    },
    [say]
  );

  return { settings, save, notice, say, saving: saving > 0, saved, refresh };
}
