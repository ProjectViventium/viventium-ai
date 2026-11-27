// Whether her voice can be heard on this page, found by trying it (core/page_sound.py says why). A browser keeps a page
// silent until the person clicks or types on it; her page opens by itself after setup, so her first greeting waits
// for this answer and the page shows one control that turns sound on (components/app/sound-on.tsx).

export type Playable = { play: () => Promise<void> | undefined | void };

// Only this refusal means "the browser keeps this page silent"; any other failure (a source changed under it) is not.
function refused(error: unknown): boolean {
  return Boolean(
    error &&
      typeof error === 'object' &&
      'name' in error &&
      (error as Error).name === 'NotAllowedError'
  );
}

// One real try on each element that carries her voice, or, before her track is on the page, on a silent sample of the
// same kind (an unmuted sound): false as soon as any is refused; true when all played, or when none was refused within
// `wait` ms (a live stream's play() waits for its first sound before it resolves, but a refusal comes at once).
export function canHear(
  elements: Playable[],
  sample: () => Playable,
  wait = 700
): Promise<boolean> {
  const tries = (elements.length ? elements : [sample()]).map((element) => {
    try {
      return Promise.resolve(element.play()).then(
        () => true,
        (error) => !refused(error)
      );
    } catch (error) {
      return Promise.resolve(!refused(error));
    }
  });
  return new Promise<boolean>((resolve) => {
    let left = tries.length;
    for (const tried of tries)
      void tried.then((ok) => {
        if (!ok) resolve(false);
        else if (--left === 0) resolve(true);
      });
    setTimeout(() => resolve(true), wait);
  });
}

// A tenth of a second of silence as a WAV file: unmuted, so the browser's rule for sound applies to it, and nothing heard.
export function silentWav(seconds = 0.1, rate = 8000): Uint8Array {
  const samples = Math.round(seconds * rate);
  const bytes = new Uint8Array(44 + samples * 2);
  const view = new DataView(bytes.buffer);
  const text = (at: number, word: string) => {
    for (let i = 0; i < word.length; i++) view.setUint8(at + i, word.charCodeAt(i));
  };
  text(0, 'RIFF');
  view.setUint32(4, 36 + samples * 2, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // (PCM)
  view.setUint16(22, 1, true); // (one channel)
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, 'data');
  view.setUint32(40, samples * 2, true);
  return bytes;
}
