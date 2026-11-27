import { NextResponse } from 'next/server';
import { execFile } from 'node:child_process';
import path from 'node:path';
import { ROOT, allowed, headers } from '../carry';

// The Memory page: what Viventium keeps about you (GET) and one look or one change (POST), both answered by its own
// module of the settings package (settings/memory.py); this route only carries JSON. (Its own route beside
// [page]: once settings/__main__.py names "memory" among the pages of their own, [page] can carry it instead.)
export const dynamic = 'force-dynamic';

function memory(args: string[], input = ''): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      path.join(ROOT, '.venv', 'bin', 'python'),
      ['-m', 'settings.memory', ...args],
      { cwd: ROOT, timeout: 20_000, maxBuffer: 4_000_000 }, // (a look or a change takes well under a second)
      (error, stdout) => {
        try {
          resolve(JSON.parse(stdout));
        } catch {
          reject(error ?? new Error('memory did not answer'));
        }
      }
    );
    child.stdin?.end(input);
  });
}

export async function GET(req: Request) {
  if (!allowed(req, false)) return new NextResponse('Not from here.', { status: 403 });
  try {
    return NextResponse.json(await memory(['show']), { headers });
  } catch {
    return new NextResponse('It could not be read.', { status: 500 });
  }
}

export async function POST(req: Request) {
  if (!allowed(req, true)) return new NextResponse('Not from here.', { status: 403 });
  try {
    const want = await req.json();
    return NextResponse.json(await memory(['apply'], JSON.stringify(want)), { headers });
  } catch {
    return NextResponse.json({ ok: false, why: 'That could not be changed.' }, { headers });
  }
}
