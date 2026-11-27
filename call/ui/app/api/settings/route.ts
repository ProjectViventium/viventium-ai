import { NextResponse } from 'next/server';
import { allowed, headers, settings } from './carry';

// Her settings: what she runs on now (GET) and saving one change (POST). Both are answered by the
// settings package (settings/service.py), the one owner of what a choice means; this route only carries JSON.
export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  if (!allowed(req, false)) return new NextResponse('Not from here.', { status: 403 });
  try {
    return NextResponse.json(await settings(['show']), { headers });
  } catch {
    return new NextResponse('Her settings could not be read.', { status: 500 });
  }
}

export async function POST(req: Request) {
  if (!allowed(req, true)) return new NextResponse('Not from here.', { status: 403 });
  try {
    const want = await req.json();
    return NextResponse.json(await settings(['apply'], JSON.stringify(want)), { headers });
  } catch {
    return NextResponse.json({ ok: false, why: 'That could not be saved.' }, { headers });
  }
}
