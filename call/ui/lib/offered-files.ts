// Which of her links the call page draws as files (components/app/file-link.tsx): the files she offered in the
// conversation, as her agent knows them from the record (call/agent.py FilesTold). Decided on the link the markdown
// renderer found, never on her text: her words, her code and the record stay exactly as she wrote them.
//
// Her local model wrote links to files no tool had offered, and made-up file targets: each of those is her
// label, plain. The page asks her agent for the whole set once it listens, so a word sent before it listened is never
// needed; until it has the set, a well-formed file link is a link, as on main. Her answer is the truth:
// the page asks again after a reconnect and whenever a link names an id it does not know (healer), so a word of hers it
// missed heals itself.

export type Offered = { known: boolean; ids: ReadonlySet<string> };
export const NOT_YET: Offered = { known: false, ids: new Set() };
const FILE = '#viv-file-';
const ID = /^[a-f0-9]{32}$/;

/** How a link of hers is drawn: 'file' (one she offered, or any well-formed one until her set is known), 'label' (her
 *  label alone: a file target that is not one she offered), or 'link' (every other link, as before). */
export function drawn(href: string | undefined, offered: Offered): 'file' | 'label' | 'link' {
  if (!href?.startsWith(FILE)) return 'link';
  const id = href.slice(FILE.length);
  if (!ID.test(id)) return 'label';
  return !offered.known || offered.ids.has(id) ? 'file' : 'label';
}

/** Her agent's word on new offers (`whole` false: what is known so far stays as it was), or her whole set. */
export function add(offered: Offered, ids: unknown, whole: boolean): Offered {
  const more = Array.isArray(ids) ? ids.filter((id): id is string => typeof id === 'string') : [];
  return { known: offered.known || whole, ids: new Set([...offered.ids, ...more]) };
}

/** Asks her agent for her whole set until it answers with a list of ids (her agent not in the room yet, or not
 *  answering yet: asked again `wait` ms later), at most `tries` times, while `here()`. True once it answered. */
export async function ask(
  answer: () => Promise<string>,
  got: (ids: string[]) => void,
  here: () => boolean,
  wait = 500,
  tries = 240
): Promise<boolean> {
  for (let n = 0; n < tries && here(); n++) {
    try {
      const ids: unknown = JSON.parse(await answer());
      if (Array.isArray(ids)) {
        if (here()) got(ids);
        return true;
      }
    } catch {
      // (asked again)
    }
    await new Promise((resolve) => setTimeout(resolve, wait));
  }
  return false;
}

/** The id a link of hers names when the page knows her set and the id is not in it (perhaps a word of hers it missed):
 *  one to ask about. */
export function unknown(href: string | undefined, offered: Offered): string | undefined {
  if (!offered.known || !href?.startsWith(FILE)) return undefined;
  const id = href.slice(FILE.length);
  return ID.test(id) && !offered.ids.has(id) ? id : undefined;
}

/** Asks for her whole set again (`ask`) when a link names an id this page does not know: once per id, `wait` ms after
 *  the first, one ask at a time, another after one in flight when an id came meanwhile. fresh(): at once, and every id
 *  may be asked about again (after a reconnect: words of hers may have been missed). */
export function healer(ask: () => Promise<unknown>, wait = 300) {
  const asked = new Set<string>();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let running = false;
  let again = false;
  let stopped = false;
  const run = async () => {
    timer = undefined;
    if (stopped) return;
    running = true;
    try {
      await ask();
    } catch {
      // (asked again with the next id it does not know)
    } finally {
      running = false;
      if (again && !stopped) {
        again = false;
        void run();
      }
    }
  };
  const soon = (ms: number) => {
    if (running) again = true;
    else if (timer === undefined) timer = setTimeout(run, ms);
  };
  return {
    unknown(id: string) {
      if (asked.has(id)) return;
      asked.add(id);
      soon(wait);
    },
    fresh() {
      asked.clear();
      soon(0);
    },
    stop() {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
    },
  };
}
