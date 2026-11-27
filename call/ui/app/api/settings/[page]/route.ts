import { NextResponse } from 'next/server';
import { allowed, headers, settings } from '../carry';

// The pages of their own (Subconscious, Scheduling, Prompts): the same two calls, each answered by its own module
// of the settings package (settings/subconscious.py, settings/scheduling.py, settings/prompts.py: shown, never changed).
export const dynamic = 'force-dynamic';

const PAGES = new Set(['subconscious', 'scheduling', 'prompts']);
type Where = { params: Promise<{ page: string }> };

export async function GET(req: Request, { params }: Where) {
  const { page } = await params;
  if (!PAGES.has(page)) return new NextResponse('No such page.', { status: 404 });
  if (!allowed(req, false)) return new NextResponse('Not from here.', { status: 403 });
  try {
    return NextResponse.json(await settings([page, 'show']), { headers });
  } catch {
    return new NextResponse('It could not be read.', { status: 500 });
  }
}

export async function POST(req: Request, { params }: Where) {
  const { page } = await params;
  if (!PAGES.has(page)) return new NextResponse('No such page.', { status: 404 });
  if (!allowed(req, true)) return new NextResponse('Not from here.', { status: 403 });
  try {
    const want = await req.json();
    return NextResponse.json(await settings([page, 'apply'], JSON.stringify(want)), { headers });
  } catch {
    return NextResponse.json({ ok: false, why: 'That could not be saved.' }, { headers });
  }
}
