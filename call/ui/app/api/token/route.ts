import { NextResponse } from 'next/server';
import {
  AccessToken,
  type AccessTokenOptions,
  RoomConfiguration,
  type VideoGrant,
} from 'livekit-server-sdk';
import { allowed, fromPhone } from '../settings/carry';
import { mindDown } from './mind';
import { paired, renewed } from './pairing';
import { claim, full, ready } from './ready';

type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
};

// Light's own LiveKit key, made once on this Mac and kept in its Keychain: ./vx gives it to this page, LiveKit and her
// agent through their environment (never a file or a command line).
const API_KEY = process.env.LIVEKIT_API_KEY;
const API_SECRET = process.env.LIVEKIT_API_SECRET;
const LIVEKIT_URL = process.env.LIVEKIT_URL;

// don't cache the results
export const revalidate = 0;

// Who may use these three: his page on this computer, as his settings (allowed() in ../settings/carry.ts), or his
// phone at the phone address once he paired it (./pairing.ts). A call's token lets whoever holds it hear and speak
// with her, so another site open in his browser, a name pointed at this computer or another device on his network
// never gets one, nor holds her restarts, nor learns whether she is up.
function caller(req: Request, writing: boolean): 'mac' | 'phone' | null {
  if (allowed(req, writing)) return 'mac';
  if (fromPhone(req, writing) && paired(req)) return 'phone';
  return null;
}
const refused = () => new NextResponse('Not from here.', { status: 403 });

// Where his phone reaches LiveKit (VX_LAN_LIVEKIT_URL, wss on his network): LIVEKIT_URL is this computer's own.
function phoneLiveKit(): string | null {
  try {
    const url = new URL(process.env.VX_LAN_LIVEKIT_URL ?? '');
    if (url.protocol !== 'wss:' || url.username || url.password) return null;
    return url.href.endsWith('/') ? url.href.slice(0, -1) : url.href;
  } catch {
    return null;
  }
}

// The call door's own address for a page to reach (https, as the phone's browser checks its certificate), or null.
function phoneDoor(): string | null {
  const lk = phoneLiveKit();
  return lk ? `https://${new URL(lk).host}/` : null;
}

// Whether she can take a call right now, and who is asking: the call page asks before it offers "Start call". "mac" is
// his page on this computer, "phone" a phone he paired; a phone at the phone address that is not paired yet is told so
// (its page then opens the pairing page, /pair) and learns nothing else. Anyone else: refused, as before. A paired
// phone also learns when Viventium's root was made new since it trusted one (its pairing page then shows the steps and
// the fingerprint), and where the call's door is, to see whether it trusts the new one yet. Both also learn when the last
// start found that her mind cannot answer until something is changed (mind: 'down', ./mind.ts): the page then says
// so at its top.
export async function GET(req: Request) {
  const who = caller(req, false);
  if (!who) {
    if (fromPhone(req, false))
      return NextResponse.json(
        { ready: false, here: 'unpaired' },
        { status: 403, headers: { 'Cache-Control': 'no-store' } }
      );
    return refused();
  }
  const fresh = who === 'phone' ? renewed(req) : null;
  const up = await ready();
  return NextResponse.json(
    {
      ready: up,
      here: who,
      ...(up && (await full()) ? { full: true } : {}), // (every conversation she takes at once is open: ready.ts)
      ...((await mindDown()) ? { mind: 'down' } : {}),
      ...(fresh ? { renewed: true, ...fresh, door: phoneDoor() } : {}),
    },
    { headers: { 'Cache-Control': 'no-store' } }
  );
}

// The page joining its conversation: waits until she can answer, and marks it as starting so a settings change holds
// its restart. (The token below is fetched by the session itself, so it cannot be what waits or what marks.) With every
// conversation she takes at once open, nothing is marked and the page is told so (429): it asks again by itself.
export async function PUT(req: Request) {
  if (!caller(req, true)) return refused();
  const claimed = await claim(45);
  if (claimed === 'full')
    return new NextResponse('Viventium has every conversation she takes at once open.', {
      status: 429,
    });
  if (claimed) return new NextResponse(null, { status: 204 });
  return new NextResponse('Viventium is still starting. Try again in a moment.', { status: 503 });
}

export async function POST(req: Request) {
  const who = caller(req, true);
  if (!who) return refused();
  const serverUrl = who === 'phone' ? phoneLiveKit() : LIVEKIT_URL;
  if (who === 'phone' && !serverUrl)
    return new NextResponse('Calls from your phone are not set up yet.', { status: 503 });

  try {
    if (serverUrl === undefined || serverUrl === null) {
      throw new Error('LIVEKIT_URL is not defined');
    }
    if (API_KEY === undefined) {
      throw new Error('LIVEKIT_API_KEY is not defined');
    }
    if (API_SECRET === undefined) {
      throw new Error('LIVEKIT_API_SECRET is not defined');
    }

    // Parse room config from request body.
    const body = await req.json();
    const roomConfig = body?.room_config
      ? RoomConfiguration.fromJson(body.room_config, { ignoreUnknownFields: true })
      : new RoomConfiguration();

    // Generate participant token
    const participantName = 'user';
    // One kind of room for every conversation (the requirement: no chat/call path separation): typing and talking
    // happen in the same room, and her agent follows his microphone (call/agent.py set_voice). Unique per page visit:
    // memory summaries and telemetry group a conversation by its room name.
    const participantIdentity = `voice_assistant_user_${who}_${crypto.randomUUID()}`;
    const roomName = `conversation_${crypto.randomUUID()}`;

    const participantToken = await createParticipantToken(
      {
        identity: participantIdentity,
        name: participantName,
      },
      roomName,
      roomConfig
    );

    // Return connection details
    const data: ConnectionDetails = {
      serverUrl,
      roomName,
      participantName,
      participantToken,
    };
    const headers = new Headers({
      'Cache-Control': 'no-store',
    });
    return NextResponse.json(data, { headers });
  } catch (error) {
    if (error instanceof Error) {
      console.error(error);
      return new NextResponse(error.message, { status: 500 });
    }
  }
}

function createParticipantToken(
  userInfo: AccessTokenOptions,
  roomName: string,
  roomConfig: RoomConfiguration | undefined
): Promise<string> {
  const at = new AccessToken(API_KEY, API_SECRET, {
    ...userInfo,
    ttl: '15m',
  });
  const grant: VideoGrant = {
    room: roomName,
    roomJoin: true,
    canPublish: process.env.STT !== 'off',
    canPublishData: true,
    canSubscribe: true,
  };
  at.addGrant(grant);

  if (roomConfig) {
    at.roomConfig = roomConfig;
  }

  return at.toJwt();
}
