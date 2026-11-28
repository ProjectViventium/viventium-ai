'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'motion/react';
import { useSessionContext } from '@livekit/components-react';
import { cn } from '@/lib/shadcn/utils';

// How she is with you on this call: Talk, Wing (quiet beside you, speaks when spoken to) or Listen only
// (hears and remembers, never speaks). A call starts the way the settings page says; this switches it live,
// for this call, by telling her agent on the call's own data channel (topic "viv.mode"). Every choice made here is told
// (a choice remembered as told was not sent again after the menu bar had changed her mode meanwhile, so
// the page showed Wing while she stayed in Listen only); her agent ignores one that changes nothing.

type Mode = { id: string; name: string; hint: string };
const MODES: Mode[] = [
  { id: 'talk', name: 'Talk', hint: 'A normal conversation.' },
  { id: 'wing', name: 'Wing', hint: 'Quiet beside you. Speaks when spoken to.' },
  { id: 'listen', name: 'Listen only', hint: 'Hears and remembers. Never speaks.' },
];

export function useCallMode() {
  const [mode, setMode] = useState('talk');
  const [modes, setModes] = useState(MODES);
  useEffect(() => {
    fetch('/api/settings', { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => {
        if (s?.call_mode) setMode(s.call_mode);
        if (s?.call_modes?.length) setModes(s.call_modes);
      })
      .catch(() => undefined);
  }, []);
  return { mode, setMode, modes };
}

// While Wing or Listen only is on, each new thing he says (a new piece of his speech-to-text, or a turn her agent heard
// and kept quiet: "viv.quiet", the mode and the turn, never the words) brings one short toast under the switch, so
// someone waiting for an answer knows why none comes, shown only when new speech-to-text arrives. The switch follows
// the mode told; the toast goes by itself, when she speaks, the mode changes to Talk
// or the microphone goes off. One toast, never two: a new turn only starts its time again.
const SHOWN_MS = 4500;
export const MODE_TOAST: Record<string, string> = {
  listen: "Listen only: I'm listening, not talking.",
  wing: "Wing mode: I'll answer when you talk to me.",
};

export function useModeToast(
  mode: string,
  setMode: (id: string) => void,
  talking: boolean,
  speaking: boolean,
  heard: string | undefined
) {
  const { room } = useSessionContext();
  const [toast, setToast] = useState<{ mode: string; at: number } | null>(null);
  const show = (quiet: string) => setToast({ mode: quiet, at: Date.now() });
  useEffect(() => {
    if (!room) return;
    room.registerTextStreamHandler('viv.quiet', async (reader) => {
      try {
        const told = JSON.parse(await reader.readAll()) as { mode?: string };
        if (told.mode === 'listen' || told.mode === 'wing') {
          setMode(told.mode);
          show(told.mode);
        }
      } catch {
        // (a message that is not one of these is left alone)
      }
    });
    return () => room.unregisterTextStreamHandler('viv.quiet');
  }, [room, setMode]);
  // (his newest piece of speech-to-text, by its own id: each new one, never an update of the same one, and never one
  // that was already there when his microphone came on)
  const seen = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!heard || heard === seen.current) return;
    seen.current = heard;
    if (talking && MODE_TOAST[mode]) show(mode);
  }, [heard, talking, mode]);
  useEffect(() => {
    if (!toast) return;
    if (!MODE_TOAST[mode] || !talking || speaking) {
      setToast(null);
      return;
    }
    const gone = setTimeout(() => setToast(null), SHOWN_MS - (Date.now() - toast.at));
    return () => clearTimeout(gone);
  }, [toast, mode, talking, speaking]);
  return toast && MODE_TOAST[mode] ? mode : null;
}

export function ModeToast({ mode }: { mode: string }) {
  return (
    <motion.div
      role="status"
      data-mode-toast={mode}
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className="fixed top-[64px] left-1/2 z-50 w-max max-w-[calc(100vw-32px)] -translate-x-1/2 rounded-full bg-amber-400/15 px-4 py-1.5 text-xs leading-4 font-medium text-amber-800 backdrop-blur-md dark:bg-amber-300/12 dark:text-amber-200"
    >
      {MODE_TOAST[mode]}
    </motion.div>
  );
}

export function CallMode({
  mode,
  modes,
  onChange,
}: {
  mode: string;
  modes: Mode[];
  onChange: (id: string) => void;
}) {
  const { room, isConnected } = useSessionContext();
  const choose = (id: string) => {
    onChange(id);
    if (isConnected && room)
      room.localParticipant.sendText(id, { topic: 'viv.mode' }).catch(() => undefined);
  };
  return (
    <div
      role="radiogroup"
      aria-label="How Viventium is on this call"
      className="bg-muted/70 border-border fixed top-5 left-1/2 z-50 flex w-max -translate-x-1/2 rounded-full border p-1 backdrop-blur-md"
    >
      {modes.map((m) => (
        <button
          key={m.id}
          type="button"
          role="radio"
          aria-checked={m.id === mode}
          title={m.hint}
          onClick={() => m.id !== mode && choose(m.id)}
          className={cn(
            'relative rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors',
            m.id === mode
              ? 'text-primary-foreground'
              : 'text-muted-foreground hover:text-foreground'
          )}
        >
          {m.id === mode && (
            <motion.span
              layoutId="call-mode"
              className="bg-primary absolute inset-0 rounded-full"
              transition={{ type: 'spring', visualDuration: 0.22, bounce: 0.22 }}
            />
          )}
          <span className="relative">{m.name}</span>
        </button>
      ))}
    </div>
  );
}
