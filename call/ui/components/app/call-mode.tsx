'use client';

import { useEffect, useState } from 'react';
import type { Room } from 'livekit-client';
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

// A turn heard and, by the call's mode, kept quiet (her agent's "viv.quiet": the mode and the turn, never the words):
// one line under the switch says so, with one tap to Talk, so a quiet mode never leaves silence unexplained. The pill
// follows the mode told; the line goes when she speaks, the mode changes or the microphone goes off.
export function useQuiet(
  mode: string,
  setMode: (id: string) => void,
  talking: boolean,
  speaking: boolean
) {
  const { room } = useSessionContext();
  const [quiet, setQuiet] = useState<string | null>(null);
  useEffect(() => {
    if (!room) return;
    room.registerTextStreamHandler('viv.quiet', async (reader) => {
      try {
        const told = JSON.parse(await reader.readAll()) as { mode?: string };
        if (told.mode === 'listen' || told.mode === 'wing') {
          setMode(told.mode);
          setQuiet(told.mode);
        }
      } catch {
        // (a message that is not one of these is left alone)
      }
    });
    return () => room.unregisterTextStreamHandler('viv.quiet');
  }, [room, setMode]);
  useEffect(() => {
    if (quiet && (quiet !== mode || !talking || speaking)) setQuiet(null);
  }, [quiet, mode, talking, speaking]);
  return quiet;
}

// Talk from the line: this call at once (as the switch does), and saved as how the next call starts, the way the menu
// bar's and the settings page's choices are kept.
export function talkNow(room: Room | undefined) {
  room?.localParticipant.sendText('talk', { topic: 'viv.mode' }).catch(() => undefined);
  fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ call_mode: 'talk' }),
  }).catch(() => undefined);
}

export function QuietLine({
  quiet,
  modes,
  onTalk,
}: {
  quiet: string;
  modes: Mode[];
  onTalk: () => void;
}) {
  const name = modes.find((m) => m.id === quiet)?.name ?? quiet;
  const said =
    quiet === 'wing'
      ? `Viventium took that as meant for someone else (${name}).`
      : `Viventium heard you and is staying quiet (${name}).`;
  return (
    <motion.div
      role="status"
      data-quiet={quiet}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className="bg-muted/70 fixed top-[60px] left-1/2 z-50 flex w-max max-w-[calc(100vw-32px)] -translate-x-1/2 items-center gap-3 rounded-2xl py-1.5 pr-1.5 pl-4 text-xs leading-4 backdrop-blur-md"
    >
      <span className="text-muted-foreground">{said}</span>
      <button
        type="button"
        onClick={onTalk}
        className="bg-primary text-primary-foreground shrink-0 rounded-full px-3.5 py-1 font-medium"
      >
        Talk
      </button>
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
