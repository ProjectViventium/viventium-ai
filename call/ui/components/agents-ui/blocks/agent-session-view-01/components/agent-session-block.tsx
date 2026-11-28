'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, type MotionProps, motion } from 'motion/react';
import { type ReceivedMessage, useAgent, useSessionContext } from '@livekit/components-react';
import { AgentChatTranscript } from '@/components/agents-ui/agent-chat-transcript';
import {
  AgentControlBar,
  type AgentControlBarControls,
} from '@/components/agents-ui/agent-control-bar';
import { MICROPHONE_FAILED } from '@/lib/live';
import { offeredOnce } from '@/lib/offered-once';
import { cn } from '@/lib/shadcn/utils';
import { microphoneSentence } from '@/lib/start-call';
import { TileLayout } from './tile-view';

const BOTTOM_VIEW_MOTION_PROPS: MotionProps = {
  variants: {
    visible: {
      opacity: 1,
      translateY: '0%',
    },
    hidden: {
      opacity: 0,
      translateY: '100%',
    },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
  transition: {
    duration: 0.3,
    delay: 0.5,
    ease: 'easeOut',
  },
};

const CHAT_MOTION_PROPS: MotionProps = {
  variants: {
    hidden: {
      opacity: 0,
      transition: {
        ease: 'easeOut',
        duration: 0.3,
      },
    },
    visible: {
      opacity: 1,
      transition: {
        delay: 0.2,
        ease: 'easeOut',
        duration: 0.3,
      },
    },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
};

interface FadeProps {
  top?: boolean;
  bottom?: boolean;
  className?: string;
}

export function Fade({ top = false, bottom = false, className }: FadeProps) {
  return (
    <div
      className={cn(
        'from-background pointer-events-none h-4 bg-linear-to-b to-transparent',
        top && 'bg-linear-to-b',
        bottom && 'bg-linear-to-t',
        className
      )}
    />
  );
}

export interface AgentSessionView_01Props {
  /**
   * Message shown above the controls before the first chat message is sent.
   *
   * @default 'Agent is listening, ask it a question'
   */
  preConnectMessage?: string;
  /**
   * Enables or disables the chat toggle and transcript input controls.
   *
   * @default true
   */
  supportsChatInput?: boolean;
  supportsAudioInput?: boolean;
  /**
   * Enables or disables camera controls in the bottom control bar.
   *
   * @default true
   */
  supportsVideoInput?: boolean;
  /**
   * Enables or disables screen sharing controls in the bottom control bar.
   *
   * @default true
   */
  supportsScreenShare?: boolean;
  /**
   * Shows a pre-connect buffer state with a shimmer message before messages appear.
   *
   * @default true
   */
  isPreConnectBufferEnabled?: boolean;

  /**
   * His microphone is on: the conversation is a call (her voice, Talk / Wing / Listen only). Off, he types. Either
   * way it is one conversation in one room: the transcript and the text box are always there, and so is she.
   *
   * @default false
   */
  talking?: boolean;
  /** How she is with him while he talks (Talk, Wing, Listen only). */
  mode?: string;
  /** Messages from before this session (the one conversation, from any channel), shown above its own. */
  earlier?: ReceivedMessage[];
  messages: ReceivedMessage[];

  /** Selects the visualizer style rendered in the main tile area. */
  audioVisualizerType?: 'bar' | 'wave' | 'grid' | 'radial';
  /** Primary hex color used by supported audio visualizer variants. */
  audioVisualizerColor?: `#${string}`;
  /** Hue shift intensity used by certain visualizers. */
  audioVisualizerColorShift?: number;
  /** Number of bars to render when `audioVisualizerType` is `bar`. */
  audioVisualizerBarCount?: number;
  /** Number of rows in the visualizer when `audioVisualizerType` is `grid`. */
  audioVisualizerGridRowCount?: number;
  /** Number of columns in the visualizer when `audioVisualizerType` is `grid`. */
  audioVisualizerGridColumnCount?: number;
  /** Number of radial bars when `audioVisualizerType` is `radial`. */
  audioVisualizerRadialBarCount?: number;
  /** Base radius of the radial visualizer when `audioVisualizerType` is `radial`. */
  audioVisualizerRadialRadius?: number;
  /** Stroke width of the wave path when `audioVisualizerType` is `wave`. */
  audioVisualizerWaveLineWidth?: number;
  /** Optional class name merged onto the outer `<section>` container. */
  className?: string;
}

export function AgentSessionView_01({
  preConnectMessage = 'Agent is listening, ask it a question',
  supportsChatInput = true,
  supportsAudioInput = true,
  supportsVideoInput = true,
  supportsScreenShare = true,
  isPreConnectBufferEnabled = true,
  talking = false,
  mode = 'talk',
  earlier,
  messages,
  audioVisualizerType,
  audioVisualizerColor,
  audioVisualizerColorShift,
  audioVisualizerBarCount,
  audioVisualizerGridRowCount,
  audioVisualizerGridColumnCount,
  audioVisualizerRadialBarCount,
  audioVisualizerRadialRadius,
  audioVisualizerWaveLineWidth,
  ref,
  className,
  ...props
}: React.ComponentProps<'section'> & AgentSessionView_01Props) {
  const session = useSessionContext();
  // (one conversation: its transcript is always open, never a toggle to find)
  const isChatOpen = true;
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const agent = useAgent();
  const agentState = agent.state;
  const identity = agent.isConnected ? agent.identity : undefined;
  const { room } = session;
  useEffect(() => {
    if (!identity) return;
    void room.localParticipant
      .sendText('ready', { topic: 'viv.transcript-ready', destinationIdentities: [identity] })
      .catch(() => {});
  }, [room, identity]);
  // (each file she offers shown once, where her words carry it: lib/offered-once.ts)
  const shown = useMemo(
    () => offeredOnce(earlier?.length ? [...earlier, ...messages] : messages),
    [earlier, messages]
  );
  // The conversation ends where the bar below begins, whatever its height (a longer text, files to send): nothing is
  // ever drawn over a message (the chat's status line sat on her last one).
  const barRef = useRef<HTMLDivElement>(null);
  const [bar, setBar] = useState(0);
  useEffect(() => {
    const el = barRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const look = new ResizeObserver(() => setBar(el.offsetHeight));
    look.observe(el);
    return () => look.disconnect();
  }, []);

  // Why his microphone could not be turned on (blocked for this page, none found, held by another app), in one plain
  // sentence above the bar until it works; typing goes on meanwhile.
  const [micProblem, setMicProblem] = useState('');
  useEffect(() => {
    if (talking) setMicProblem('');
  }, [talking]);
  useEffect(() => {
    // (the menu bar's Ears asked for it and it could not be turned on: the same sentence, lib/live.ts)
    const said = (event: Event) => setMicProblem(microphoneSentence((event as CustomEvent).detail));
    window.addEventListener(MICROPHONE_FAILED, said);
    return () => window.removeEventListener(MICROPHONE_FAILED, said);
  }, []);

  const controls: AgentControlBarControls = {
    leave: false, // (nothing to end: the microphone button ends talking, and the page is the conversation)
    microphone: supportsAudioInput,
    chat: false,
    camera: supportsVideoInput,
    screenShare: supportsScreenShare,
  };

  useEffect(() => {
    const lastMessage = messages.at(-1);
    const lastMessageIsLocal = lastMessage?.from?.isLocal === true;

    if (scrollAreaRef.current && lastMessageIsLocal) {
      scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <section
      ref={ref}
      className={cn('bg-background relative z-10 h-full w-full overflow-hidden', className)}
      {...props}
    >
      <Fade top className="absolute inset-x-4 top-0 z-10 h-40" />
      {/* transcript */}
      <AnimatePresence>
        {isChatOpen && (
          <motion.div
            {...CHAT_MOTION_PROPS}
            className="absolute inset-x-0 top-0 bottom-[135px] overflow-hidden md:bottom-[170px]"
            style={bar ? { bottom: bar } : undefined}
          >
            <AgentChatTranscript
              agentState={agentState}
              messages={shown}
              onApprovalReply={(text, code) =>
                room.localParticipant.sendText(text, {
                  topic: 'lk.chat',
                  attributes: { 'viv.approval.choice': code },
                })
              }
              className="mx-auto max-w-2xl **:data-[slot=message-scroller-content]:p-4 **:data-[slot=message-scroller-content]:pt-40! md:**:data-[slot=message-scroller-content]:p-6"
            />
            {/* What is happening, in plain words where the messages will be, only while there is none: it never
                covers one (Viventium joining, then how to begin) */}
            {shown.length === 0 && (
              <p
                role="status"
                className="text-muted-foreground pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 px-6 text-center text-sm font-medium motion-safe:animate-pulse"
              >
                {preConnectMessage}
              </p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Her presence: always there, small above the conversation (the dots, or Soulface where it is added) */}
      <TileLayout
        isChatOpen={isChatOpen}
        talking={talking}
        mode={mode}
        audioVisualizerType={audioVisualizerType}
        audioVisualizerColor={audioVisualizerColor}
        audioVisualizerColorShift={audioVisualizerColorShift}
        audioVisualizerBarCount={audioVisualizerBarCount}
        audioVisualizerRadialBarCount={audioVisualizerRadialBarCount}
        audioVisualizerRadialRadius={audioVisualizerRadialRadius}
        audioVisualizerGridRowCount={audioVisualizerGridRowCount}
        audioVisualizerGridColumnCount={audioVisualizerGridColumnCount}
        audioVisualizerWaveLineWidth={audioVisualizerWaveLineWidth}
      />
      {/* Bottom */}
      <motion.div
        ref={barRef}
        {...BOTTOM_VIEW_MOTION_PROPS}
        className="absolute inset-x-3 bottom-0 z-50 md:inset-x-12"
      >
        <div className="bg-background relative mx-auto max-w-2xl pb-3 md:pb-12">
          {micProblem && (
            <p
              role="alert"
              className="text-muted-foreground px-4 pb-2 text-center text-sm leading-5"
            >
              {micProblem}
            </p>
          )}
          <AgentControlBar
            variant="livekit"
            controls={controls}
            isChatOpen={isChatOpen}
            isConnected={session.isConnected}
            waiting={!agent.isConnected}
            busy={agentState === 'thinking' || agentState === 'speaking'}
            onDeviceError={({ source, error }) => {
              if (source === 'microphone') setMicProblem(microphoneSentence(error));
            }}
            onDisconnect={session.end}
          />
        </div>
      </motion.div>
    </section>
  );
}
