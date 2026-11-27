'use client';

import { type ComponentProps } from 'react';
import { Streamdown, defaultRemarkPlugins } from 'streamdown';
import { type AgentState, type ReceivedMessage } from '@livekit/components-react';
import { AgentChatIndicator } from '@/components/agents-ui/agent-chat-indicator';
import { AttachedFiles, type SentFile } from '@/components/app/attached-files';
import { FileLink } from '@/components/app/file-link';
import { type ApprovalReply, WorkerApproval } from '@/components/app/worker-approval';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { Marker, MarkerContent, MarkerIcon } from '@/components/ui/marker';
import { Message, MessageContent } from '@/components/ui/message';
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller';
import { numbersAsText } from '@/lib/her-numbers';

// Every line break she wrote is a line break on screen. Markdown reads a single one inside a paragraph or a list item
// as a space; this turns each into a real break, after Streamdown's own steps (GFM, math, CJK). Her code keeps its own
// lines (code is not text here), and markdown's own line breaks around a list's paragraphs and nested lists stay unseen,
// so her lists look as they always did (keeping every line break in a list item's layout broke them).
type MarkdownNode = {
  type: string;
  value?: string;
  url?: string;
  alt?: string;
  children?: MarkdownNode[];
};
function plainArtifactLinks() {
  const visit = (node: MarkdownNode) => {
    if (!node.children) return;
    node.children = node.children.flatMap((child) => {
      visit(child);
      if (!child.url?.startsWith('artifact_sha256:')) return [child];
      if (child.type === 'link') return child.children ?? [];
      if (child.type === 'image') return [{ type: 'text', value: child.alt ?? '' }];
      return [child];
    });
  };
  return visit;
}
function keepLineBreaks() {
  const visit = (node: MarkdownNode) => {
    if (!node.children) return;
    node.children = node.children.flatMap((child) => {
      if (child.type !== 'text' || !child.value?.includes('\n')) {
        visit(child);
        return [child];
      }
      return child.value
        .split('\n')
        .flatMap((part, n) => [
          ...(n ? [{ type: 'break' }] : []),
          ...(part ? [{ type: 'text', value: part }] : []),
        ]);
    });
  };
  return (tree: MarkdownNode) => visit(tree);
}
const HER_MARKDOWN = [
  ...Object.values(defaultRemarkPlugins),
  plainArtifactLinks,
  numbersAsText,
  keepLineBreaks,
];

function approvalCode(message: ReceivedMessage): string {
  if (message.attributes?.['viv.approval'] !== '3') return '';
  try {
    const code = JSON.parse(message.message)?.approval?.code;
    return typeof code === 'string' ? code : '';
  } catch {
    return '';
  }
}

/**
 * Props for the AgentChatTranscript component.
 */
export interface AgentChatTranscriptProps
  extends ComponentProps<'div'>,
    ComponentProps<typeof MessageScrollerProvider>,
    ComponentProps<typeof MessageScrollerViewport>,
    ComponentProps<typeof MessageScrollerContent> {
  /**
   * Whether to automatically scroll to the bottom of the transcript when new messages are added.
   * @defaultValue true
   */
  autoScroll?: boolean;
  onApprovalReply?: ApprovalReply;
  /**
   * The scroll anchor to use when auto-scrolling.
   * @defaultValue false
   */
  scrollAnchor?: boolean | 'user' | 'other' | 'any';
  /**
   * The scroll button render function
   */
  scrollButtonRender?: ComponentProps<typeof MessageScrollerButton>['render'];
  /**
   * The scroll button behavior
   */
  scrollButtonBehavior?: ComponentProps<typeof MessageScrollerButton>['behavior'];
  /**
   * The scroll button direction
   */
  scrollButtonDirection?: ComponentProps<typeof MessageScrollerButton>['direction'];
  /**
   * The current state of the agent. When 'thinking', displays a loading indicator.
   */
  agentState?: AgentState;
  /**
   * Array of messages to display in the transcript.
   * @defaultValue []
   */
  messages?: ReceivedMessage[];
  /**
   * Additional CSS class names to apply to the conversation container.
   */
  className?: string;
}

/**
 * A chat transcript component that displays a conversation between the user and agent.
 * Shows messages with timestamps and origin indicators, plus a thinking indicator
 * when the agent is processing.
 *
 * @extends ComponentProps<'div'>, ComponentProps<typeof MessageScrollerProvider>, ComponentProps<typeof MessageScrollerViewport>, ComponentProps<typeof MessageScrollerContent>
 *
 *
 * @example
 * ```tsx
 * <AgentChatTranscript
 *   agentState={agentState}
 *   messages={chatMessages}
 * />
 * ```
 */
export function AgentChatTranscript({
  scrollAnchor,
  autoScroll = true,
  onApprovalReply,
  scrollMargin,
  scrollEdgeThreshold,
  preserveScrollOnPrepend,
  scrollPreviousItemPeek,
  defaultScrollPosition = 'last-anchor',
  scrollButtonRender,
  scrollButtonBehavior,
  scrollButtonDirection,
  spacerClassName,
  agentState,
  messages = [],
  className,
  ...props
}: AgentChatTranscriptProps) {
  const codes = new Set(messages.map(approvalCode).filter(Boolean));
  const results = new Map(
    messages
      .filter((m) => !m.from?.isLocal && m.attributes?.['viv.approval.code'])
      .map((m) => [m.attributes!['viv.approval.code'], m.message])
  );
  return (
    <MessageScrollerProvider
      autoScroll={autoScroll}
      scrollMargin={scrollMargin}
      defaultScrollPosition={defaultScrollPosition}
      scrollEdgeThreshold={scrollEdgeThreshold}
      scrollPreviousItemPeek={scrollPreviousItemPeek}
    >
      <MessageScroller className={className} {...props}>
        <MessageScrollerViewport preserveScrollOnPrepend={preserveScrollOnPrepend}>
          <MessageScrollerContent
            spacerClassName={spacerClassName}
            aria-busy={agentState === 'thinking'}
          >
            {messages.map((receivedMessage) => {
              const { id, timestamp, from, message } = receivedMessage;
              if (
                receivedMessage.attributes?.['viv.approval.choice'] ||
                (receivedMessage.attributes?.['viv.approval.code'] &&
                  codes.has(receivedMessage.attributes['viv.approval.code']))
              )
                return null;
              const time = new Date(timestamp);
              const isUser = from?.isLocal;
              const approvalFormat = receivedMessage.attributes?.['viv.approval'];
              const locale = typeof navigator !== 'undefined' ? navigator.language : 'en-US';
              const title = time.toLocaleTimeString(locale, { timeStyle: 'full' });
              let _scrollAnchor = false;

              if (
                scrollAnchor === 'any' ||
                (scrollAnchor === 'user' && isUser) ||
                (scrollAnchor === 'other' && !isUser)
              ) {
                _scrollAnchor = true;
              }

              return (
                <MessageScrollerItem key={id} messageId={id} scrollAnchor={_scrollAnchor}>
                  <Message align={isUser ? 'end' : 'start'} title={title}>
                    <MessageContent>
                      <Bubble
                        align={isUser ? 'end' : 'start'}
                        variant={isUser ? 'secondary' : 'ghost'}
                      >
                        <BubbleContent>
                          {/* Files sent with a chat message (LiveKit's attachments), above its words */}
                          <AttachedFiles
                            files={
                              (receivedMessage as { attachedFiles?: SentFile[] }).attachedFiles ??
                              []
                            }
                            className={message ? 'mb-1' : undefined}
                          />
                          {/* His words exactly as he typed them (pasted code too: never read as markdown), every
                              line break and space kept. Hers keep their markdown, with every line break she wrote
                              (HER_MARKDOWN), read as written: Streamdown's repair of unfinished markdown added a stray _
                              after code with _ in it (while she is still writing, an unclosed mark shows for a moment). */}
                          {message &&
                            (approvalFormat === '1' ||
                            approvalFormat === '2' ||
                            approvalFormat === '3' ? (
                              <WorkerApproval
                                message={message}
                                structured={approvalFormat !== '1'}
                                onReply={onApprovalReply}
                                result={results.get(approvalCode(receivedMessage))}
                              />
                            ) : isUser ? (
                              <p className="[overflow-wrap:anywhere] whitespace-pre-wrap">
                                {message}
                              </p>
                            ) : (
                              <Streamdown
                                components={{ a: FileLink }}
                                parseIncompleteMarkdown={false}
                                remarkPlugins={HER_MARKDOWN}
                              >
                                {message}
                              </Streamdown>
                            ))}
                        </BubbleContent>
                      </Bubble>
                    </MessageContent>
                  </Message>
                </MessageScrollerItem>
              );
            })}

            {/* Agent is thinking indicator */}
            {agentState === 'thinking' && (
              <MessageScrollerItem>
                <Marker role="status">
                  <MarkerIcon>
                    <AgentChatIndicator size="sm" />
                  </MarkerIcon>
                  <MarkerContent className="shimmer">Thinking...</MarkerContent>
                </Marker>
              </MessageScrollerItem>
            )}
          </MessageScrollerContent>
        </MessageScrollerViewport>

        {/* Scroll to bottom button */}
        <MessageScrollerButton
          variant="outline"
          className="rounded-full"
          render={scrollButtonRender}
          behavior={scrollButtonBehavior}
          direction={scrollButtonDirection}
        />
      </MessageScroller>
    </MessageScrollerProvider>
  );
}
