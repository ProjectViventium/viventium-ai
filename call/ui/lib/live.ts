// What the menu bar changes on this conversation, live (her ears, eyes, Wing and Listen
// only). Her agent follows it and tells the page on the room's own text stream (topic "viv.live", call/agent.py
// menu_asked; core/live.py): the microphone on or off (her agent then follows the microphone, as it always does), the
// mode to show, or a look again at how she is shown (Soulface or the dots). Typed state only; no imports, so it runs as
// it is in Node too (tests/live_ask.mjs).

export type Live = { ears?: boolean; mode?: string; presence?: string };

export const LOOK_AGAIN = 'viv:look'; // (presence.tsx looks again at once)
export const MICROPHONE_FAILED = 'viv:microphone-failed'; // (said where the microphone button's own failures are)

/** What one message from her agent asks of the page: each part done by the page's own controls. */
export function liveAsk(
  said: Live,
  page: { microphone: (on: boolean) => unknown; mode: (id: string) => void; look: () => void }
): void {
  if (typeof said.ears === 'boolean') page.microphone(said.ears);
  if (typeof said.mode === 'string' && said.mode) page.mode(said.mode);
  if (typeof said.presence === 'string') page.look();
}
