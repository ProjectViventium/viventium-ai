'use client';

import { useTheme } from 'next-themes';
import Link from 'next/link';
import { AnimatePresence, motion } from 'motion/react';
import {
  useAgent,
  useLocalParticipant,
  useSessionContext,
  useSessionMessages,
} from '@livekit/components-react';
import { AgentSessionView_01 } from '@/components/agents-ui/blocks/agent-session-view-01';
import { CallMode, QuietLine, talkNow, useCallMode, useQuiet } from '@/components/app/call-mode';
import { useEarlier } from '@/components/app/earlier';
import { useOfferedFiles } from '@/components/app/file-link';
import { useLive } from '@/components/app/live';
import { Mark } from '@/components/app/mark';

const MotionSessionView = motion.create(AgentSessionView_01);

const VIEW_MOTION_PROPS = {
  variants: {
    visible: {
      opacity: 1,
    },
    hidden: {
      opacity: 0,
    },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
  transition: {
    duration: 0.5,
    ease: 'linear',
  },
};

interface ViewControllerProps {
  isVideoInputSupported: boolean;
  /** Why joining did not work yet, in plain words ('' when none); the page asks again by itself. */
  problem?: string;
  /** Ask again now instead of waiting. */
  onRetry?: () => void;
}

export function ViewController({
  isVideoInputSupported,
  problem = '',
  onRetry,
}: ViewControllerProps) {
  const session = useSessionContext();
  const { isConnected } = session;
  // Listen before the opening animation yields to the transcript. A Worker can already be waiting.
  const { messages } = useSessionMessages(session);
  const { isMicrophoneEnabled, localParticipant } = useLocalParticipant();
  const voiceAvailable = localParticipant.permissions?.canPublish !== false;
  const agent = useAgent();
  const { resolvedTheme } = useTheme();
  const { mode, setMode, modes } = useCallMode();
  useLive(setMode); // (the menu bar's ears, Wing and Listen only, and eyes, through her agent: live.ts)
  const earlier = useEarlier(isConnected);
  useOfferedFiles(isConnected); // (which of her links name files she sent: file-link.tsx)
  // One conversation: typing works at once; the microphone makes it a call in the same room, and only then does how
  // she is with you while talking (Talk, Wing, Listen only) show.
  const talking = isConnected && isMicrophoneEnabled;
  const quiet = useQuiet(mode, setMode, talking, agent.state === 'speaking');
  const waiting: Record<string, string> = {
    talk: 'Viventium is listening. Say hello.',
    wing: 'Viventium is beside you, quiet until spoken to.',
    listen: 'Viventium is here with you, just listening.',
  };

  return (
    <>
      {/* (its own presence: in "wait" mode below, a child leaving shows only the leaving ones until it has gone) */}
      <AnimatePresence>
        {talking && quiet && (
          <QuietLine
            key="call-quiet"
            quiet={quiet}
            modes={modes}
            onTalk={() => {
              setMode('talk');
              talkNow(session.room);
            }}
          />
        )}
      </AnimatePresence>
      <AnimatePresence mode="wait">
        {talking && <CallMode key="call-mode" mode={mode} modes={modes} onChange={setMode} />}
        {/* Joining: her mark and, only when something is in the way, one plain sentence; it asks again by itself */}
        {!isConnected && (
          <motion.section
            key="joining"
            {...VIEW_MOTION_PROPS}
            className="bg-background flex flex-col items-center justify-center text-center"
          >
            <Mark size={124} />
            <p role="status" className="text-muted-foreground mt-3 max-w-xs text-sm leading-5">
              {problem || 'Viventium is joining...'}
            </p>
            <div className="mt-6 flex items-center gap-6 text-xs font-medium tracking-wide">
              {problem && onRetry && (
                <button
                  type="button"
                  onClick={onRetry}
                  className="text-muted-foreground hover:text-foreground cursor-pointer transition-colors"
                >
                  Try now
                </button>
              )}
              <Link href="/settings" className="text-muted-foreground hover:text-foreground">
                Settings
              </Link>
            </div>
          </motion.section>
        )}
        {/* The conversation */}
        {isConnected && (
          <MotionSessionView
            key="session-view"
            {...VIEW_MOTION_PROPS}
            talking={talking}
            mode={mode}
            earlier={earlier}
            messages={messages}
            preConnectMessage={
              !agent.isConnected
                ? 'Viventium is joining...'
                : talking
                  ? waiting[mode]
                  : voiceAvailable
                    ? 'Type, or press the microphone to talk.'
                    : 'Type to Viventium.'
            }
            supportsChatInput={true}
            supportsAudioInput={voiceAvailable}
            supportsVideoInput={isVideoInputSupported}
            supportsScreenShare={isVideoInputSupported}
            isPreConnectBufferEnabled={true}
            audioVisualizerColor={resolvedTheme === 'dark' ? '#e2c69c' : '#b8a184'}
            className="fixed inset-0"
          />
        )}
      </AnimatePresence>
    </>
  );
}
