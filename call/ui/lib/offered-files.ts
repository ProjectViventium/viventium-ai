// Which of her links the call page draws as files (components/app/file-link.tsx): the files she offered in the
// conversation, as her agent knows them from the record (call/agent.py FilesTold). Decided on the link the markdown
// renderer found, never on her text: her words, her code and the record stay exactly as she wrote them.
//
// Her local model wrote links to files no tool had offered, and made-up file targets: each of those is her
// label, plain. The page asks her agent for the whole set once it listens, so a word sent before it listened is never
// needed; until it has the set, a well-formed file link is a link, as on main. Her answer is the truth:
// the page asks again after a reconnect and whenever a link names an id it does not know (healer), so a word of hers it
// missed heals itself.

// Pictures: which of her offers the page draws as themselves, beside their links (her agent's word, from each file's
// own type: core/attachments.py picture), never decided on her words for them.
export type Offered = { known: boolean; ids: ReadonlySet<string>; pictures: ReadonlySet<string> };
export const NOT_YET: Offered = { known: false, ids: new Set(), pictures: new Set() };
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

const strings = (list: unknown): string[] =>
  Array.isArray(list) ? list.filter((id): id is string => typeof id === 'string') : [];

/** Her agent's word on new offers (`whole` false: what is known so far stays as it was), or her whole set; with which
 *  of them are pictures. */
export function add(offered: Offered, ids: unknown, whole: boolean, pictures?: unknown): Offered {
  return {
    known: offered.known || whole,
    ids: new Set([...offered.ids, ...strings(ids)]),
    pictures: new Set([...offered.pictures, ...strings(pictures)]),
  };
}

/** Her agent's answer to the page's ask: her whole set, as {ids, pictures}, or a plain list of ids (an agent from before
 *  pictures). Anything else is no answer. */
export function answered(answer: unknown): { ids: string[]; pictures: string[] } | undefined {
  if (Array.isArray(answer)) return { ids: strings(answer), pictures: [] };
  if (answer && typeof answer === 'object' && Array.isArray((answer as { ids?: unknown }).ids)) {
    const { ids, pictures } = answer as { ids: unknown; pictures?: unknown };
    return { ids: strings(ids), pictures: strings(pictures) };
  }
  return undefined;
}

/** Whether a link of hers is drawn as a picture: a file she offered that her agent says is one. */
export function picture(href: string | undefined, offered: Offered): boolean {
  return drawn(href, offered) === 'file' && offered.pictures.has(href!.slice(FILE.length));
}

/** What the page's ask sends her agent (RPC "viv.files"): that this page reads which files are pictures, so her agent
 *  answers {ids, pictures}. A page that sends nothing (one from before pictures) gets the plain list (call/agent.py
 *  FilesTold.answer). */
export const ASK = JSON.stringify({ pictures: true });

/** Asks her agent for her whole set until it answers (her agent not in the room yet, or not answering yet: asked again
 *  `wait` ms later), at most `tries` times, while `here()`. True once it answered with her set. An answer in a shape this
 *  page cannot read is still her answer: never asked again, so every file link stays a link, as before her set is known
 *  (release 60: a page opened before the update asked again every half second until its tries ran out). */
export async function ask(
  answer: () => Promise<string>,
  got: (ids: string[], pictures: string[]) => void,
  here: () => boolean,
  wait = 500,
  tries = 240
): Promise<boolean> {
  for (let n = 0; n < tries && here(); n++) {
    let reply: string;
    try {
      reply = await answer();
    } catch {
      await new Promise((resolve) => setTimeout(resolve, wait)); // (asked again)
      continue;
    }
    let set: ReturnType<typeof answered>;
    try {
      set = answered(JSON.parse(reply));
    } catch {
      set = undefined;
    }
    if (set && here()) got(set.ids, set.pictures);
    return set !== undefined;
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
