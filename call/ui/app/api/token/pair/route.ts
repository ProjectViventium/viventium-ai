import { NextResponse } from 'next/server';
import { allowed, fromPhone } from '../../settings/carry';
import { newCode, redeem, trusted } from '../pairing';

// Pairing his phone (../pairing.ts): his Mac's own page asks for a code to show (this computer only), and his phone,
// at the phone address, types it once.
export const dynamic = 'force-dynamic';
const headers = { 'Cache-Control': 'no-store' };

export async function POST(req: Request) {
  if (!allowed(req, true)) return new NextResponse('Not from here.', { status: 403 });
  let made;
  try {
    made = await newCode();
  } catch {
    return new NextResponse('Viventium could not keep a code privately on this Mac.', {
      status: 503,
      headers,
    });
  }
  if (!made) return new NextResponse('Calling from your phone is off.', { status: 409, headers });
  return NextResponse.json(made, { headers });
}

export async function PUT(req: Request) {
  if (!fromPhone(req, true)) return new NextResponse('Not from here.', { status: 403 });
  let body: { code?: unknown; trusted?: unknown } = {};
  try {
    body = await req.json();
  } catch {
    /* (no code) */
  }
  if (body?.trusted === true) {
    // (a paired phone whose page reached the call's door with Viventium's new root: its cookie marks that root now)
    const renewed = await trusted(req);
    return renewed
      ? new NextResponse(null, { status: 204, headers: { ...headers, 'Set-Cookie': renewed } })
      : new NextResponse('This phone is not paired.', { status: 403, headers });
  }
  const cookie = await redeem(body?.code);
  if (!cookie)
    return new NextResponse('That code did not work. Ask your Mac for a new one.', {
      status: 403,
      headers,
    });
  return new NextResponse(null, { status: 204, headers: { ...headers, 'Set-Cookie': cookie } });
}
