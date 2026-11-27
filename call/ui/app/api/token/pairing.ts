import { createHash, createHmac, randomBytes, randomInt, timingSafeEqual } from 'node:crypto';
import { promises as fs, readFileSync } from 'node:fs';
import path from 'node:path';
import { lanOrigin } from '../settings/carry';
import { STATE, privateFolder, writePrivate } from './private';

// Pairing his phone, for calls from the same Wi-Fi. His Mac's own page asks for a code (this computer only, pair/);
// he types it once on his phone; the phone gets a long-lived cookie for the call's routes only (HttpOnly, Secure,
// SameSite=Strict), signed with Light's own pairing secret (made once and kept in the Keychain: ./vx gives it to this
// page as VX_PHONE_SECRET) and bound to the phone address and to the pairings of now (ROUND, below). It also says which
// of Viventium's roots the phone trusted then (a short mark, not a secret), so a root made new since is said on the
// phone (pair/page.tsx) until it trusts the new one. Every request from the phone shows it again.
const COOKIE = 'vx_phone';
const CODE_LIFE = 5 * 60_000; // ms a code may be typed in
const TRIES = 5; // wrong codes before it is void
const LETTERS = '23456789ABCDEFGHJKMNPQRSTVWXYZ'; // (no 0 O 1 I L U: easy to read out and type)
const PENDING = path.join(STATE, 'core', 'phone-pairing.json'); // the code waiting to be typed: its hash only
// Which round of pairings a cookie must belong to (not a secret): made with the first pairing, and made new by Forget
// paired phones (settings/runtime.py forget_phones()), so every phone paired before stops at its next request, with no
// restart. Read at every check; none (never paired): no phone is paired.
const ROUND = path.join(STATE, 'core', 'phone', 'paired');
const ROOT_CRT = path.join(STATE, 'core', 'phone', 'root.crt'); // (call/phone.py: the root the phone trusts)
// Which root each paired phone trusts, by its cookie's id (not a secret): his Mac's Phone tile says when one needs the
// new root (settings/service.py), since a phone that trusts only the old one can load nothing over the new certificate.
const TRUSTED = path.join(STATE, 'core', 'phone', 'trusted.json');
async function keepTrusted(id: string, mark: string): Promise<void> {
  let kept: Record<string, string> = {};
  try {
    kept = JSON.parse(await fs.readFile(TRUSTED, 'utf8'));
  } catch {
    /* (none yet) */
  }
  await writePrivate(TRUSTED, JSON.stringify({ ...kept, [id]: mark })).catch(() => {});
}

const secret = () =>
  (process.env.VX_PHONE_SECRET ?? '').length >= 32 ? process.env.VX_PHONE_SECRET! : null;
const digest = (code: string) => createHash('sha256').update(code).digest('hex');
const sign = (key: string, origin: string, turn: string, id: string, root: string) =>
  createHmac('sha256', key).update(`${origin}\n${turn}\n${id}\n${root}`).digest('base64url');

// Viventium's root now: a short mark of it ("-": none yet), and its SHA-256 fingerprint as a phone shows it.
function rootNow(): { mark: string; fingerprint: string } {
  try {
    const pem = readFileSync(ROOT_CRT, 'utf8');
    const der = Buffer.from(pem.replace(/-----[^-]+-----/g, '').replace(/\s+/g, ''), 'base64');
    const hex = createHash('sha256').update(der).digest('hex').toUpperCase();
    return { mark: hex.slice(0, 16), fingerprint: hex.match(/../g)!.join(' ') };
  } catch {
    return { mark: '-', fingerprint: '' };
  }
}
function round(): string | null {
  try {
    const now = readFileSync(ROUND, 'utf8').trim();
    return now.length >= 16 ? now : null;
  } catch {
    return null;
  }
}

function same(a: string, b: string): boolean {
  const [x, y] = [Buffer.from(a), Buffer.from(b)];
  return x.length === y.length && timingSafeEqual(x, y);
}

// The phone's cookie, when its signature holds for the phone address set now, since he last forgot paired phones.
function shown(req: Request): { id: string; root: string } | null {
  const key = secret();
  const lan = lanOrigin();
  const now = round();
  if (!key || !lan || !now) return null;
  const kept = (req.headers.get('cookie') ?? '')
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${COOKIE}=`));
  const [id, root, mac, more] = (kept?.slice(COOKIE.length + 1) ?? '').split('.');
  return id && root && mac && more === undefined && same(mac, sign(key, lan.origin, now, id, root))
    ? { id, root }
    : null;
}

// A phone he paired: its cookie holds (whichever root it trusted then: a new root never unpairs it).
export function paired(req: Request): boolean {
  return shown(req) !== null;
}

function cookie(key: string, origin: string, turn: string, id: string): string {
  const root = rootNow().mark;
  return `${COOKIE}=${id}.${root}.${sign(key, origin, turn, id, root)}; Path=/api/token; Max-Age=31536000; HttpOnly; Secure; SameSite=Strict`;
}

// For a paired phone: Viventium's root made new since it was paired (null when not), with its new fingerprint.
export function renewed(req: Request): { fingerprint: string } | null {
  const was = shown(req);
  const now = rootNow();
  return was && was.root !== now.mark ? { fingerprint: now.fingerprint } : null;
}

// The paired phone trusts the root of now (its page reached the call's door with it): its cookie says so from now on.
export async function trusted(req: Request): Promise<string | null> {
  const was = shown(req);
  const key = secret();
  const lan = lanOrigin();
  const now = round();
  if (!was || !key || !lan || !now) return null;
  await keepTrusted(was.id, rootNow().mark);
  return cookie(key, lan.origin, now, was.id);
}

// A new code for his phone, asked by his Mac's own page: one at a time, for a few minutes and a few tries.
export async function newCode(): Promise<{ code: string; until: number } | null> {
  if (!secret() || !lanOrigin()) return null;
  const code = Array.from({ length: 8 }, () => LETTERS[randomInt(LETTERS.length)]).join('');
  const until = Date.now() + CODE_LIFE;
  await writePrivate(PENDING, JSON.stringify({ hash: digest(code), until, tries: 0 }));
  return { code, until };
}

// The phone typed a code: right, in time and within its tries, the code is spent and the phone gets its cookie
// (the Set-Cookie value); otherwise null. A try takes the waiting code whole first (a rename: one at a time), so two
// at once can never both spend it; a wrong one puts it back with one try less, unless a new code came meanwhile.
export async function redeem(code: unknown): Promise<string | null> {
  const key = secret();
  const lan = lanOrigin();
  if (!key || !lan || typeof code !== 'string') return null;
  const taken = `${PENDING}.${randomBytes(8).toString('hex')}`;
  try {
    await privateFolder(path.dirname(PENDING));
    await fs.rename(PENDING, taken);
  } catch {
    return null;
  }
  let pending: { hash?: string; until?: number; tries?: number } = {};
  try {
    pending = JSON.parse(await fs.readFile(taken, 'utf8'));
  } catch {
    /* (unreadable: spent) */
  }
  await fs.rm(taken, { force: true });
  const tries = Number(pending.tries) || 0;
  if (!(Number(pending.until) > Date.now()) || tries >= TRIES) return null;
  if (!same(digest(code.trim().toUpperCase()), String(pending.hash))) {
    if (tries + 1 < TRIES)
      await writePrivate(PENDING, JSON.stringify({ ...pending, tries: tries + 1 }), {
        exclusive: true,
      }).catch(() => {});
    return null;
  }
  // (the first pairing, or the first since a restore: its round is made; one made meanwhile is kept)
  if (!round())
    await writePrivate(ROUND, randomBytes(16).toString('hex'), { exclusive: true }).catch(() => {});
  const now = round();
  if (!now) return null;
  const id = randomBytes(16).toString('base64url');
  await keepTrusted(id, rootNow().mark);
  return cookie(key, lan.origin, now, id);
}
