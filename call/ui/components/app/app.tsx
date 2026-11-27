'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { TokenSource } from 'livekit-client';
import { useSession } from '@livekit/components-react';
import { WarningIcon } from '@phosphor-icons/react/dist/ssr';
import { AgentSessionProvider } from '@/components/agents-ui/agent-session-provider';
import { MindLine } from '@/components/app/mind-line';
import { SoundOn } from '@/components/app/sound-on';
import { ViewController } from '@/components/app/view-controller';
import { Toaster } from '@/components/ui/sonner';
import { useSpeakerOff } from '@/hooks/use-speaker';
import { useAgentErrors } from '@/hooks/useAgentErrors';
import { useDebugMode } from '@/hooks/useDebug';
import { open, ready } from '@/lib/start-call';

const IN_DEVELOPMENT = process.env.NODE_ENV !== 'production';

// How long the page waits before it asks again, while Viventium is still starting or after the room closed (a restart):
// the conversation comes back by itself, nobody has to press anything.
const AGAIN_MS = 3000;

// After this many failed starts in a row her side is not coming up by itself: the page stops asking (every ask holds a
// settings restart back, and a restart may be what fixes it) and says so, with one way to ask again.
const MOST_FAILURES = 3;

function AppSetup({ onFailed, onHere }: { onFailed: () => void; onHere: () => void }) {
  useDebugMode({ enabled: IN_DEVELOPMENT });
  useAgentErrors({ onFailed, onHere });

  return null;
}

interface AppProps {
  tokenServerId?: string;
  tokenEndpoint: string;
  agentName?: string;
  isVideoInputSupported: boolean;
}

export function App({ tokenServerId, tokenEndpoint, agentName, isVideoInputSupported }: AppProps) {
  const tokenSource = useMemo(
    () =>
      tokenServerId
        ? TokenSource.developmentTokenServer(tokenServerId)
        : TokenSource.endpoint(tokenEndpoint),
    [tokenServerId, tokenEndpoint]
  );

  // The page is the conversation (the requirement: no "start call" step, no chat/call path separation). It joins at
  // once with the microphone off: typing works straight away, and the microphone button makes it a call in the same
  // room (her agent follows the microphone: call/agent.py set_voice). In order, leaving nothing open when a step fails
  // (lib/start-call.ts): she can answer (app/api/token PUT: it waits until Viventium can answer and holds a settings
  // restart back), then the room. While she is still starting, or after the room closed (a restart), the page says so
  // in one plain sentence and asks again by itself.
  const session = useSession(tokenSource, agentName ? { agentName } : {});
  const { start, end, room, connectionState } = session;
  const [problem, setProblem] = useState('');
  const [round, setRound] = useState(0); // (each try to join; a failed one schedules the next)
  const joining = useRef(false);
  const mounted = useRef(true);
  const joined = useRef(false); // (it was in the room before: a rejoin after a restart waits a moment first)
  const failures = useRef(0); // (her side failed to start this many times in a row: each rejoin waits longer)
  const wasFull = useRef(false); // (the last answer was that every conversation she takes at once is open)
  const onFailed = useCallback(() => {
    failures.current += 1;
  }, []);
  const onHere = useCallback(() => {
    failures.current = 0;
  }, []);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (connectionState !== 'disconnected') {
      if (connectionState === 'connected') joined.current = true;
      return;
    }
    if (joining.current) return;
    if (failures.current >= MOST_FAILURES) {
      setProblem('Viventium could not answer. Try now, or open Settings.');
      return;
    }
    joining.current = true;
    const later = () =>
      setTimeout(() => {
        if (mounted.current) setRound((n) => n + 1);
      }, AGAIN_MS);
    (async () => {
      if (joined.current) {
        joined.current = false;
        // (after a restart, a moment; after failed starts, longer each time: 1, 2, 4 s)
        await new Promise((resolve) => setTimeout(resolve, (AGAIN_MS / 3) * 2 ** failures.current));
      }
      const said = await ready(true, {
        microphone: async () => undefined, // (the microphone is asked for only when he turns it on)
        claim: async () => {
          // A phone that is not paired yet goes to its pairing page (/pair) and learns nothing else (app/api/token GET).
          const look = await fetch('/api/token', { cache: 'no-store' })
            .then((reply) => reply.json())
            .catch(() => null);
          if (look?.here === 'unpaired') {
            window.location.replace('/pair');
            return false;
          }
          // Every conversation she takes at once is open (app/api/token: her agent's own load): said, nothing claimed, and
          // asked again by itself. She is up and answering, so a room she did not join before this is no failure of hers.
          const busy = () => {
            failures.current = 0;
            wasFull.current = true;
            return 'full' as const;
          };
          if (look?.full) return busy();
          if (wasFull.current) {
            // A place came free: LiveKit's server hears of it at her next status, within 1.5 s (agents/worker.py
            // UPDATE_STATUS_INTERVAL), and a room opened before that never gets her. One status later, then on.
            wasFull.current = false;
            await new Promise((resolve) => setTimeout(resolve, 2000));
          }
          return fetch('/api/token', { method: 'PUT' }).then((reply) =>
            reply.status === 429 ? busy() : reply.ok
          );
        },
      });
      if (!mounted.current) return;
      if (said) {
        setProblem(said);
        later();
        return;
      }
      const failed = await open(true, {
        connect: () => start({ tracks: { microphone: { enabled: false } } }),
        microphoneOn: async () => undefined,
        close: async () => {
          const tracks = [...room.localParticipant.trackPublications.values()].map(
            (pub) => pub.track
          );
          try {
            await end();
          } finally {
            tracks.forEach((track) => track?.stop());
          }
        },
      });
      if (!mounted.current) return;
      // A room that could not open is a failed start too: after a few in a row the page stops asking, so a join that
      // keeps failing at once never keeps her call mark (app/api/token claim) and with it a settings restart held.
      if (failed) failures.current += 1;
      setProblem(failed);
      if (failed) later();
    })().finally(() => {
      joining.current = false;
    });
  }, [connectionState, round, start, end, room]);

  const speakerOff = useSpeakerOff(); // (the bar's speaker: off, nothing of hers plays here)
  return (
    <AgentSessionProvider session={session} muted={speakerOff}>
      <AppSetup onFailed={onFailed} onHere={onHere} />
      <main className="grid h-svh grid-cols-1 place-content-center">
        <ViewController
          isVideoInputSupported={isVideoInputSupported}
          problem={problem}
          onRetry={() => {
            failures.current = 0;
            setRound((n) => n + 1);
          }}
        />
      </main>
      {/* Sound off in this browser until a click: one plain control, and her first hello waits for it */}
      <SoundOn />
      {/* The last start found her mind cannot answer: one line at the top, whatever else shows */}
      <MindLine />
      <Toaster
        icons={{
          warning: <WarningIcon weight="bold" />,
        }}
        position="top-center"
        className="toaster group"
        style={
          {
            '--normal-bg': 'var(--popover)',
            '--normal-text': 'var(--popover-foreground)',
            '--normal-border': 'var(--border)',
          } as React.CSSProperties
        }
      />
    </AgentSessionProvider>
  );
}
