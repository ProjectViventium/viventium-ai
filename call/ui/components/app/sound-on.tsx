'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ParticipantKind, type Room, RoomEvent } from 'livekit-client';
import { Volume2 } from 'lucide-react';
import { useSessionContext } from '@livekit/components-react';
import { canHear, silentWav } from '@/lib/sound';

// Her voice on this page, never spoken into silence (core/page_sound.py). Before her first greeting she asks
// ("viv.sound"): the page tries her own track and answers "on" or "off". While the browser keeps the page silent, one
// plain control shows; it, or any first click or key press on the page, starts sound in that same gesture (LiveKit's
// room.startAudio), and the page tells her ("viv.sound" text) so she greets. It replaces LiveKit's 'Start Audio'
// button, which sat below the full-height page where nobody saw it.

function herElements(room: Room): HTMLMediaElement[] {
  return [...room.remoteParticipants.values()]
    .filter((person) => person.kind === ParticipantKind.AGENT)
    .flatMap((person) => [...person.audioTrackPublications.values()])
    .flatMap((publication) => publication.track?.attachedElements ?? []);
}

function sample(): HTMLAudioElement {
  const url = URL.createObjectURL(new Blob([silentWav() as BlobPart], { type: 'audio/wav' }));
  const element = new Audio(url);
  element.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true });
  return element;
}

export function SoundOn() {
  const { room } = useSessionContext();
  const [off, setOff] = useState(false);
  const silent = useRef(false); // (the same, for the gesture listeners)

  const mark = useCallback((value: boolean) => {
    silent.current = value;
    setOff(value);
  }, []);

  const tell = useCallback(() => {
    if (!room) return;
    const agent = [...room.remoteParticipants.values()].find(
      (person) => person.kind === ParticipantKind.AGENT
    );
    room.localParticipant
      .sendText('on', {
        topic: 'viv.sound',
        ...(agent ? { destinationIdentities: [agent.identity] } : {}),
      })
      .catch(() => undefined);
  }, [room]);

  // In the person's own click or key press: LiveKit plays every attached track now, then the page tries hers again.
  const turnOn = useCallback(() => {
    if (!room || !silent.current) return;
    const started = room.startAudio();
    const unlocked = sample().play(); // (the same gesture: a page with no track of hers yet is allowed too)
    void Promise.allSettled([started, unlocked]).then(async () => {
      if (room.canPlaybackAudio && (await canHear(herElements(room), sample))) {
        mark(false);
        tell();
      }
    });
  }, [room, mark, tell]);

  useEffect(() => {
    if (!room) return;
    const status = () => {
      if (!room.canPlaybackAudio) mark(true);
    };
    room.on(RoomEvent.AudioPlaybackStatusChanged, status);
    room.registerRpcMethod('viv.sound', async () => {
      const on = room.canPlaybackAudio && (await canHear(herElements(room), sample));
      mark(!on);
      return on ? 'on' : 'off';
    });
    const events = ['mousedown', 'keydown', 'touchend'] as const;
    for (const name of events) window.addEventListener(name, turnOn, true);
    return () => {
      room.off(RoomEvent.AudioPlaybackStatusChanged, status);
      room.unregisterRpcMethod('viv.sound');
      for (const name of events) window.removeEventListener(name, turnOn, true);
    };
  }, [room, mark, turnOn]);

  if (!off) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 top-1/2 z-50 flex justify-center px-4">
      <button
        type="button"
        onClick={turnOn}
        className="bg-foreground text-background pointer-events-auto inline-flex h-11 items-center gap-2 rounded-full px-6 text-sm font-medium shadow-lg transition-opacity hover:opacity-90 focus-visible:outline-none"
      >
        <Volume2 className="size-4" aria-hidden />
        Turn on sound
      </button>
    </div>
  );
}
