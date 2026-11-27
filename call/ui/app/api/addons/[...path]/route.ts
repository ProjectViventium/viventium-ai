import { NextResponse } from 'next/server';
import { createHash } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { ROOT, allowed } from '../../settings/carry';

// An add-on's own files (Soulface: settings/install.py ADDONS), for this page only. An add-on is never part of Light:
// it lives in her state, in state/addons/ID, only once its person asked for it. A file is served only when the
// add-on's own list (addon.json) names it and it still has the SHA-256 that list gives: anything else is refused, so a
// changed or stray file never runs in the page.
export const dynamic = 'force-dynamic';

const STATE = process.env.VX_STATE ?? path.join(ROOT, 'state');
const TYPES: Record<string, string> = {
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.wasm': 'application/wasm',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
};
const ID = /^[a-z][a-z0-9-]{0,40}$/;
const no = (status: number, why: string) => new NextResponse(why, { status });

// (a file checked once is not hashed again until it, or the fingerprint its list gives it, changes)
const checked = new Map<string, { at: number; size: number; digest: string }>();

type Where = { params: Promise<{ path: string[] }> };

export async function GET(req: Request, { params }: Where) {
  if (!allowed(req, false)) return no(403, 'Not from here.');
  const [id, ...parts] = (await params).path ?? [];
  if (!id || !ID.test(id) || !parts.length) return no(404, 'No such add-on.');
  const folder = path.join(STATE, 'addons', id);
  let files: Record<string, string>;
  try {
    const manifest = JSON.parse(await readFile(path.join(folder, 'addon.json'), 'utf8'));
    if (manifest?.id !== id || typeof manifest.files !== 'object')
      throw new Error('not this add-on');
    files = manifest.files;
  } catch {
    return no(404, 'That add-on is not on this Mac.');
  }
  const rel = parts.join('/');
  const digest = files[rel];
  const type = TYPES[path.extname(rel).toLowerCase()];
  const file = path.resolve(folder, rel);
  if (!digest || !type || !file.startsWith(folder + path.sep)) return no(404, 'No such file.');
  try {
    const info = await stat(file);
    const data = await readFile(file);
    const seen = checked.get(file);
    if (!seen || seen.at !== info.mtimeMs || seen.size !== info.size || seen.digest !== digest) {
      if (createHash('sha256').update(data).digest('hex') !== digest) {
        checked.delete(file);
        return no(409, 'That file was changed since it was added.');
      }
      checked.set(file, { at: info.mtimeMs, size: info.size, digest });
    }
    return new NextResponse(new Uint8Array(data), {
      headers: {
        'Content-Type': type,
        'Cache-Control': 'no-cache',
        'X-Content-Type-Options': 'nosniff',
      },
    });
  } catch {
    return no(404, 'No such file.');
  }
}
