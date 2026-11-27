import { useEffect } from 'react';
import { useAgent, useSessionContext } from '@livekit/components-react';

// When her side of the room fails (a restart, or she could not answer), the room is closed; the page then says so in
// its own place and joins again by itself (components/app/app.tsx), so there is nothing to press and no toast to read.
// The library's own reason goes to the console for whoever debugs.
export function useAgentErrors({
  onFailed,
  onHere,
}: { onFailed?: () => void; onHere?: () => void } = {}) {
  const agent = useAgent();
  const { isConnected, end } = useSessionContext();

  useEffect(() => {
    if (isConnected && agent.state === 'failed') {
      console.warn('conversation ended:', agent.failureReasons);
      onFailed?.();
      end();
    }
  }, [agent, isConnected, end, onFailed]);
  useEffect(() => {
    if (isConnected && agent.isConnected) onHere?.(); // (she joined: a failure before this one is behind us)
  }, [isConnected, agent.isConnected, onHere]);
}
