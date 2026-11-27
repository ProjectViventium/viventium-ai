'use client';

import { useEffect, useRef, useState } from 'react';
import { Track } from 'livekit-client';
import {
  type TrackReference,
  useLocalParticipant,
  useTrackVolume,
  useVoiceAssistant,
} from '@livekit/components-react';
import { LOOK_AGAIN } from '@/lib/live';
import { cn } from '@/lib/shadcn/utils';

// How she shows above the conversation: the dots (built in), or Soulface where the person chose it in Settings. Soulface
// is an add-on, never part of Light (the requirement: it is heavy and extra, so someone who does not want it never
// has to download it or have it at all): it is on this Mac only once asked for
// (settings/install.py ADDONS), served from her state by app/api/addons, and loaded only when it is the one shown. The
// page talks to it through one small contract (mount, update, destroy) and sends it only typed state: what she is
// doing, how he is with her, the levels of the voices really heard and played, and her Feelings as they are.

type Choice = { shown: 'dots' | 'soulface'; entry?: string; bands: Record<string, number> };
type Band = { id: string; now: number };
type Handle = {
  ok: boolean;
  update: (state: object) => void;
  setTheme: (t: string) => void;
  destroy: () => void;
};

const NONE: Choice = { shown: 'dots', bands: {} };
const LOOK_AGAIN_MS = 60_000; // (her Feelings move over minutes; a look each minute, and when the page is back in view)

export function usePresence(): Choice {
  const [choice, setChoice] = useState<Choice>(NONE);
  useEffect(() => {
    let on = true;
    const look = () =>
      fetch('/api/settings', { cache: 'no-store' })
        .then((reply) => (reply.ok ? reply.json() : null))
        .then((s) => {
          if (!on || !s) return;
          const bands: Record<string, number> = {};
          for (const band of (s.character?.bands ?? []) as Band[]) bands[band.id] = band.now;
          setChoice({
            shown: s.presence?.shown === 'soulface' ? 'soulface' : 'dots',
            entry: s.presence?.soulface?.entry,
            bands,
          });
        })
        .catch(() => undefined);
    look();
    const timer = setInterval(
      () => document.visibilityState === 'visible' && look(),
      LOOK_AGAIN_MS
    );
    const back = () => document.visibilityState === 'visible' && look();
    document.addEventListener('visibilitychange', back);
    window.addEventListener(LOOK_AGAIN, look); // (chosen from the menu bar or Settings meanwhile: shown at once)
    return () => {
      on = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', back);
      window.removeEventListener(LOOK_AGAIN, look);
    };
  }, []);
  return choice;
}

// Her state as Soulface's activities (its State slot): what LiveKit says she is doing, and whether he is talking.
function activityOf(agentState: string, talking: boolean): string {
  switch (agentState) {
    case 'speaking':
      return 'speaking';
    case 'thinking':
      return 'thinking';
    case 'listening':
      return talking ? 'listening' : 'present';
    case 'connecting':
    case 'initializing':
      return 'waiting';
    case 'failed':
    case 'disconnected':
      return 'resting';
    default:
      return 'present';
  }
}

interface SoulfaceProps {
  entry: string;
  talking: boolean;
  mode: string;
  bands: Record<string, number>;
  themeMode?: 'dark' | 'light';
  /** It could not be shown (no WebGL, a file refused): the page shows the dots instead. */
  onFailed: () => void;
  className?: string;
}

export function Soulface({
  entry,
  talking,
  mode,
  bands,
  themeMode,
  onFailed,
  className,
}: SoulfaceProps) {
  const box = useRef<HTMLDivElement>(null);
  const handle = useRef<Handle | null>(null);
  const { state: agentState, audioTrack } = useVoiceAssistant();
  const { localParticipant, microphoneTrack } = useLocalParticipant();
  const mic: TrackReference | undefined = microphoneTrack
    ? {
        participant: localParticipant,
        publication: microphoneTrack,
        source: Track.Source.Microphone,
      }
    : undefined;
  const heard = useTrackVolume(mic);
  const played = useTrackVolume(audioTrack);
  // the latest state and theme, so a soul that finishes loading starts from them, not from its own defaults
  const latest = useRef<object>({});
  const theme = useRef(themeMode ?? 'dark');
  latest.current = {
    activity: activityOf(agentState, talking),
    participation: talking ? mode : 'talk',
    audio: { in: talking ? heard : 0, out: played },
    bands,
  };
  theme.current = themeMode ?? 'dark';

  useEffect(() => {
    let gone = false;
    const url = `/api/addons/soulface/${entry}`;
    import(/* webpackIgnore: true */ /* turbopackIgnore: true */ url)
      .then((module) => module.mount(box.current, { theme: theme.current }))
      .then((made: Handle) => {
        if (gone || !made.ok) {
          made.destroy(); // (whatever it made, a drawing context included, is let go)
          if (!gone) onFailed();
          return;
        }
        handle.current = made;
        made.setTheme(theme.current);
        made.update(latest.current);
      })
      .catch(() => !gone && onFailed());
    return () => {
      gone = true;
      handle.current?.destroy();
      handle.current = null;
    };
    // (mounted once per entry; the theme and state follow through update below)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry]);

  useEffect(() => {
    handle.current?.setTheme(themeMode ?? 'dark');
  }, [themeMode]);

  useEffect(() => {
    handle.current?.update(latest.current);
  }, [agentState, talking, mode, heard, played, bands]);

  return <div ref={box} aria-hidden="true" className={cn('pointer-events-none', className)} />;
}
