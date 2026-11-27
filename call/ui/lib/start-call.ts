// Starting a call or a typed chat, in an order that leaves nothing open when a step fails (a granted
// permission is not a working microphone, and a failed start had left the room or the microphone
// open). A call first takes the microphone for a moment to know it works, then claims the call; then the room opens
// with the microphone off, and only then is the microphone turned on. Whatever fails closes everything it opened and
// gives one plain sentence; the page shows it with Try again. No step here knows the page: each is given (app.tsx), so
// the order is tested on its own (tests/call_page_test.py).

export const SAY = {
  noBrowser: 'This browser cannot use a microphone. Open Viventium in Chrome or Safari.',
  blocked:
    'Viventium cannot hear you: the microphone is blocked for this page. Allow it (the icon at the left of the address bar), then try again.',
  missing: 'No microphone was found. Connect one, then try again.',
  busy: 'Another app is using the microphone. Close it, then try again.',
  starting: 'Viventium is still starting. It joins by itself when ready.',
  full: 'Viventium has as many conversations open as this Mac takes at once. Close one you no longer use; this one opens by itself.',
  failed: 'Viventium could not be reached yet. Trying again.',
};

// What a refused microphone means, in his words (the browser's own error names); anything else: the call failed.
export function microphoneSentence(error: unknown): string {
  const name =
    error && typeof error === 'object' && 'name' in error ? String((error as Error).name) : '';
  if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError')
    return SAY.blocked;
  if (
    name === 'NotFoundError' ||
    name === 'OverconstrainedError' ||
    name === 'DevicesNotFoundError'
  )
    return SAY.missing;
  if (name === 'NotReadableError' || name === 'AbortError' || name === 'TrackStartError')
    return SAY.busy;
  return SAY.failed;
}

export class StartProblem extends Error {}

type Media = { getUserMedia?: (constraints: MediaStreamConstraints) => Promise<MediaStream> };

// The microphone taken for a moment and let go: it works now (a permission granted earlier says nothing about a
// microphone unplugged or held by another app since).
export async function microphone(media: Media | undefined): Promise<void> {
  if (!media?.getUserMedia) throw new StartProblem(SAY.noBrowser);
  let stream: MediaStream;
  try {
    stream = await media.getUserMedia({ audio: true });
  } catch (error) {
    throw new StartProblem(microphoneSentence(error));
  }
  stream.getTracks().forEach((track) => track.stop()); // (the call opens its own)
  if (!stream.getAudioTracks().length) throw new StartProblem(SAY.missing);
}

export type Before = {
  microphone: () => Promise<void>; // microphone() above, for a call
  // the call claimed (app/api/token PUT): Viventium can answer; 'full': every conversation she takes at once is open
  claim: () => Promise<boolean | 'full'>;
};

// Before the room opens: '' when it may open, else the sentence to show.
export async function ready(typed: boolean, steps: Before): Promise<string> {
  try {
    if (!typed) await steps.microphone();
  } catch (error) {
    return error instanceof StartProblem ? error.message : SAY.failed;
  }
  const claimed = await steps.claim().catch(() => false);
  return claimed === 'full' ? SAY.full : claimed ? '' : SAY.starting;
}

export type Open = {
  connect: () => Promise<void>; // the session started with the microphone off
  microphoneOn: () => Promise<void>; // then the call's microphone on (LiveKit's own, with its pre-connect buffer)
  close: () => Promise<void>; // the session ended and every track it opened stopped
};

// The room, then (a call) the microphone: '' when both are open, else everything closed and the sentence to show.
export async function open(typed: boolean, steps: Open): Promise<string> {
  try {
    await steps.connect();
  } catch {
    await steps.close().catch(() => undefined);
    return SAY.failed;
  }
  if (typed) return '';
  try {
    await steps.microphoneOn();
    return '';
  } catch (error) {
    await steps.close().catch(() => undefined);
    return microphoneSentence(error);
  }
}
