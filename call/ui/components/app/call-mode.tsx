'use client';

import { useEffect, useState } from 'react';
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
      className="bg-muted/70 border-border fixed top-5 left-1/2 z-50 flex -translate-x-1/2 rounded-full border p-1 backdrop-blur-md"
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
