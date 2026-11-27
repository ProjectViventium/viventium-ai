import { NextResponse } from 'next/server';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { allowed, fromPhone } from '../../api/settings/carry';
import { STATE } from '../../api/token/private';

// Viventium's own root certificate, for his phone to trust once (call/phone.py made it, for this Mac's name on his
// network only): public, and the only file this route ever reads. To his phone at the phone address, or to his Mac
// (to send it over by AirDrop). Its key never leaves her state.
export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  if (!fromPhone(req, false) && !allowed(req, false))
    return new NextResponse('Not from here.', { status: 403 });
  let body: Buffer;
  try {
    body = await fs.readFile(path.join(STATE, 'core', 'phone', 'root.crt'));
  } catch {
    return new NextResponse('Calling from your phone is not on yet.', { status: 404 });
  }
  return new NextResponse(new Uint8Array(body), {
    headers: {
      'Content-Type': 'application/x-x509-ca-cert',
      'Content-Disposition': 'attachment; filename="Viventium.crt"',
      'Cache-Control': 'no-store',
    },
  });
}
