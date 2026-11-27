import { App } from '@/components/app/app';

// Where a call or a chat gets its token: this page's own endpoint (app/api/token), which serves this
// computer only. The template this page came from fell back to LiveKit's public homepage agent whenever
// LIVEKIT_URL was not set when the page was built: a build without it (a fresh checkout) then sent Start
// call, microphone and all, to livekit.com. That fallback is gone; without its settings the endpoint
// answers with an error and nothing leaves this Mac. (LIVEKIT_TOKEN_SERVER_ID, LiveKit Cloud's development
// token server, is still honoured when someone sets it on purpose.)
const tokenServerId = process.env.LIVEKIT_TOKEN_SERVER_ID;

export default function Page() {
  return (
    <App
      tokenServerId={tokenServerId}
      tokenEndpoint="/api/token"
      agentName={process.env.AGENT_NAME}
      isVideoInputSupported={false} // Viventium hears and speaks; she does not see video (yet)
    />
  );
}
