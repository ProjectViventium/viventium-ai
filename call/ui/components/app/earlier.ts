'use client';

import { useEffect, useState } from 'react';
import { type ReceivedMessage, useSessionContext } from '@livekit/components-react';

// A typed chat opens on the last of the one conversation, from any channel: when her agent joins it sends
// what she herself remembers of it (topic "viv.history", call/agent.py). Shown above the chat's own messages,
// so a chat reads as the same relationship going on, not as a blank page.

// (files: what the record keeps of a file he sent, never its path or what was read from it)
type Said = {
  t: number;
  role: 'user' | 'assistant';
  text: string;
  files?: { name: string; type: string; bytes: number }[];
};

export function useEarlier(on: boolean): ReceivedMessage[] {
  const { room } = useSessionContext();
  const [earlier, setEarlier] = useState<ReceivedMessage[]>([]);
  useEffect(() => {
    if (!on || !room) return;
    let here = true;
    room.registerTextStreamHandler('viv.history', async (reader) => {
      try {
        const said: Said[] = JSON.parse(await reader.readAll());
        if (!here) return;
        setEarlier(
          said.map(
            (item, n) =>
              ({
                id: `earlier-${n}`,
                timestamp: item.t * 1000,
                // (what she put in a call's chat was simply shown there, as it is here)
                message: item.text.replace(/^\(in the chat\) /, ''),
                attachedFiles: (item.files ?? []).map((f) => ({
                  name: f.name,
                  size: f.bytes,
                  type: f.type,
                })),
                type: item.role === 'user' ? 'chatMessage' : 'agentTranscript',
                from: item.role === 'user' ? room.localParticipant : undefined,
              }) as unknown as ReceivedMessage
          )
        );
      } catch {
        // only a courtesy: the chat works without it
      }
    });
    return () => {
      here = false;
      room.unregisterTextStreamHandler('viv.history');
    };
  }, [on, room]);
  return on ? earlier : [];
}
