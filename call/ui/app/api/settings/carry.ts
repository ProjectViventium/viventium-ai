import { execFile } from 'node:child_process';
import { timingSafeEqual } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';

// What every route of this page shares: who may call it, and how it asks the settings package (the one owner of
// what a choice means). A route only carries JSON.

const cwd = process.cwd();
export const ROOT =
  process.env.VX_ROOT ??
  (cwd.endsWith(path.join('call', 'ui')) ? path.resolve(cwd, '..', '..') : cwd);

const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]']);
const SAFE = new Set(['GET', 'HEAD']); // (every other method changes something)

const bare = (url: URL) =>
  !url.username && !url.password && url.pathname === '/' && !url.search && !url.hash;

// Only a page served for this computer by ./vx (LOCAL_ONLY=1, the bench too), or a developer's own server.
const served = () => process.env.LOCAL_ONLY === '1' || process.env.NODE_ENV === 'development';

// Asked the way his browser asks from that origin: its fetch metadata says same-origin (or a typed address), its
// Origin, when sent, is that origin, and a change names that origin and comes in a form a browser sends another site
// only after asking first (JSON for a POST: a form or plain text could be posted from anywhere).
function sameOrigin(req: Request, origin: string, writing: boolean): boolean {
  const site = req.headers.get('sec-fetch-site');
  if (site && site !== 'same-origin' && site !== 'none') return false;
  const sent = req.headers.get('origin');
  if (sent && sent !== origin) return false;
  if (writing || !SAFE.has(req.method)) {
    if (!sent) return false;
    const type = (req.headers.get('content-type') ?? '').toLowerCase();
    if (req.method === 'POST' && !type.startsWith('application/json')) return false;
  }
  return true;
}

// The phone's page door (call/phone.py) carries a request from his network only with this mark, set to the pass of the
// door's own start (kept in her state, his alone: read at every request, so a new start of the door is known at once).
// A request with the mark came from the network, whatever its Host says: never this computer.
const DOOR = 'x-viventium-door';
const PASS = path.join(
  process.env.VX_STATE ?? path.join(ROOT, 'state'),
  'core',
  'phone',
  'door-pass'
);
function throughDoor(req: Request): boolean {
  const said = req.headers.get(DOOR);
  let pass = '';
  try {
    pass = readFileSync(PASS, 'utf8').trim();
  } catch {
    return false; // (no door has started: nothing came through one)
  }
  const [a, b] = [Buffer.from(said ?? ''), Buffer.from(pass)];
  return pass.length >= 32 && a.length === b.length && timingSafeEqual(a, b);
}

// His page on this computer: http, a loopback name and the port this server itself listens on (Next sets PORT when it
// starts: 3400 for his Light, 3500 for the bench, a test's own; 3400, vx's own, when nothing says), and not through the
// phone's door. Her settings, what her brain did and the call from his Mac answer only this. Another site open in his
// browser, a name pointed at this computer (DNS rebinding), another page or port of this computer, anything from the
// network (a Host naming this computer sent through the door too): refused.
export function allowed(req: Request, writing: boolean): boolean {
  if (!served() || req.headers.has(DOOR)) return false;
  let url: URL;
  try {
    url = new URL(`http://${req.headers.get('host') ?? ''}`);
  } catch {
    return false;
  }
  if (!bare(url) || !LOOPBACK.has(url.hostname) || url.port !== (process.env.PORT || '3400'))
    return false;
  return sameOrigin(req, url.origin, writing);
}

// His phone on the same Wi-Fi, when calling from it is on: exactly one https address on his own network
// (VX_LAN_ORIGIN, e.g. https://my-mac.local:3443; read at every request). Anything else in it, or nothing: off.
export function lanOrigin(): URL | null {
  const value = process.env.VX_LAN_ORIGIN?.trim();
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && bare(url) && !LOOPBACK.has(url.hostname) ? url : null;
  } catch {
    return null;
  }
}

// A request from that address, carried by the phone's door (its pass), asked the way his phone's browser asks. Only the
// call's own routes take it, and only from a phone he paired (app/api/token/pairing.ts); everything else stays on this
// computer. (The page itself listens on this computer only: the door is the one way in from his network.)
export function fromPhone(req: Request, writing: boolean): boolean {
  const lan = lanOrigin();
  if (!served() || !lan || (req.headers.get('host') ?? '').toLowerCase() !== lan.host) return false;
  return throughDoor(req) && sameOrigin(req, lan.origin, writing);
}

export function settings(args: string[], input = ''): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      path.join(ROOT, '.venv', 'bin', 'python'),
      ['-m', 'settings', ...args],
      { cwd: ROOT, timeout: 240_000, maxBuffer: 2_000_000 },
      (error, stdout) => {
        try {
          resolve(JSON.parse(stdout));
        } catch {
          reject(error ?? new Error('settings did not answer'));
        }
      }
    );
    child.stdin?.end(input);
  });
}

export const headers = { 'Cache-Control': 'no-store' };
