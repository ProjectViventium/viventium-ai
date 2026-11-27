import { promises as fs } from 'node:fs';
import path from 'node:path';
import { STATE, writePrivate } from './private';

// Can she take a call this second? A room only gets her if she was registered with LiveKit before it opened,
// and right after a start or a settings change she needs a few seconds. Her agent answers "OK" on its own
// health page once LiveKit knows her (call/agent.py); a settings change that is restarting her says so in
// logs/settings-pending.json (settings/runtime.py).

const cwd = process.cwd();
const ROOT =
  process.env.VX_ROOT ??
  (cwd.endsWith(path.join('call', 'ui')) ? path.resolve(cwd, '..', '..') : cwd);
const LOGS = path.join(process.env.VX_SETTINGS_ROOT ?? ROOT, 'logs');
const LIVE = path.join(STATE, 'core', 'call-live');
// (and the page's own mark among those who hold it, so a room that ends meanwhile leaves it: core/state.py)
const HOLDS = path.join(STATE, 'core', 'call-live.d', 'page');
const HEALTH = `http://127.0.0.1:${process.env.AGENT_PORT ?? '8870'}/`;

async function restarting(): Promise<boolean> {
  try {
    const pending = JSON.parse(await fs.readFile(path.join(LOGS, 'settings-pending.json'), 'utf8'));
    return pending?.state === 'restarting';
  } catch {
    return false;
  }
}

export async function ready(): Promise<boolean> {
  if (await restarting()) return false;
  try {
    return (await fetch(HEALTH, { cache: 'no-store', signal: AbortSignal.timeout(1500) })).ok;
  } catch {
    return false;
  }
}

// Whether she has every conversation she takes at once open already: her agent's own load on LiveKit's worker page
// (/worker, beside its health page) is at FULL_LOAD, which is call/agent.py FULL (tests/call_page_test.py holds them
// equal). Every open page holds one conversation, typed or not, and a room opened then never gets her: LiveKit gives a
// room its agent once, when it opens. Unknown (an agent without that page, or not answering): not full, so the page
// tries, and a room she did not join is left and asked again (components/app/app.tsx).
const FULL_LOAD = 0.65;

export async function full(): Promise<boolean> {
  try {
    const worker = await (
      await fetch(`${HEALTH}worker`, { cache: 'no-store', signal: AbortSignal.timeout(1500) })
    ).json();
    return Number(worker?.worker_load) >= FULL_LOAD;
  } catch {
    return false;
  }
}

// A call is starting: the same mark her agent keeps while a call is on (core/state.py), so a settings change
// waits for the call instead of restarting her under it. Then one more look, in case a restart began just before.
// The mark is his alone and never written through a link (private.ts), and the click never waits for the check that
// allows it (refused while that is not in): refused, the call still starts, and the page's log says why.
// With every conversation she takes at once open, nothing is marked ('full'): looked at right before each mark, so a
// page that cannot get her never holds a restart back. (The page also stops asking after a few joins that failed:
// components/app/app.tsx.)
export async function claim(seconds: number): Promise<boolean | 'full'> {
  const until = Date.now() + seconds * 1000;
  for (;;) {
    if (await ready()) {
      if (await full()) return 'full';
      // Its own mark among those who hold call-live first, then the shared one (core/state.py release_call: a room
      // ending meanwhile, which looks under its lock, then sees this one before the shared mark can be lost).
      for (const mark of [HOLDS, LIVE])
        await writePrivate(mark, '', { wait: false }).catch((error) =>
          console.error(`call mark not written: ${error}`)
        );
      if (!(await restarting())) return true;
    }
    if (Date.now() > until) return false;
    await new Promise((done) => setTimeout(done, 400));
  }
}
