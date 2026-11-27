'use client';

import { useEffect, useRef } from 'react';
import { useSessionContext } from '@livekit/components-react';
import { LOOK_AGAIN, type Live, MICROPHONE_FAILED, liveAsk } from '@/lib/live';

// The page's side of what the menu bar changes on this conversation (lib/live.ts): her agent's messages on the room's
// "viv.live" text stream, each done by the page's own controls.
export function useLive(onMode: (id: string) => void) {
  const { room } = useSessionContext();
  const mode = useRef(onMode);
  mode.current = onMode;
  useEffect(() => {
    if (!room) return;
    room.registerTextStreamHandler('viv.live', async (reader) => {
      try {
        liveAsk(JSON.parse(await reader.readAll()) as Live, {
          microphone: (on) =>
            room.localParticipant
              .setMicrophoneEnabled(on)
              .catch((error) =>
                window.dispatchEvent(new CustomEvent(MICROPHONE_FAILED, { detail: error }))
              ),
          mode: (id) => mode.current(id),
          look: () => window.dispatchEvent(new Event(LOOK_AGAIN)),
        });
      } catch {
        // (a message that is not one of these is left alone)
      }
    });
    return () => room.unregisterTextStreamHandler('viv.live');
  }, [room]);
}
