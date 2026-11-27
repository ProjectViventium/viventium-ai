'use client';

// Mute playback on this device while keeping the microphone and transcript active.
// The call bar shares this setting with room audio. Each new page starts with sound on.
import { useSyncExternalStore } from 'react';

let off = false;
const listeners = new Set<() => void>();

export function setSpeakerOff(value: boolean): void {
  off = value;
  for (const listener of listeners) listener();
}

export function useSpeakerOff(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => off,
    () => false
  );
}
