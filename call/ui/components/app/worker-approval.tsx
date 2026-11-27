'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';

export type ApprovalReply = (text: string, code: string) => Promise<unknown>;

/** Presentation only. The agent checks the exact reply, page, request, preview and expiry. */
export function WorkerApproval({
  message,
  structured,
  result,
  onReply,
}: {
  message: string;
  structured: boolean;
  result?: string;
  onReply?: ApprovalReply;
}) {
  let text = message;
  let fullRequest = '';
  let approval:
    | { code: string; expires_at: number; choices: string[]; job_scope?: string }
    | undefined;
  if (structured) {
    text = 'The full request could not be shown.';
    try {
      const payload = JSON.parse(message);
      if (typeof payload?.text === 'string' && typeof payload?.request === 'string') {
        text = payload.text;
        fullRequest = payload.request;
        const a = payload.approval;
        if (
          /^[a-f0-9]{10}$/.test(a?.code) &&
          typeof a?.expires_at === 'number' &&
          Number.isFinite(a.expires_at) &&
          Array.isArray(a?.choices) &&
          a.choices.every((c: unknown) => typeof c === 'string') &&
          (a.job_scope === undefined ||
            (typeof a.job_scope === 'string' && a.job_scope.length < 40))
        )
          approval = a;
      }
    } catch {
      // Malformed requests offer no action.
    }
  }
  const [now, setNow] = useState(Date.now());
  const [sending, setSending] = useState(false);
  const locked = useRef(false);
  const [error, setError] = useState('');
  const expires = approval?.expires_at;
  useEffect(() => {
    if (!expires) return;
    const tick = () => setNow(Date.now());
    tick();
    const timer = setInterval(tick, 250);
    return () => clearInterval(timer);
  }, [expires]);
  const expired = !!approval && now >= approval.expires_at * 1000;
  const settled =
    result === 'Allowed once.'
      ? 'Allowed'
      : result === 'Denied.'
        ? 'Denied'
        : result?.startsWith('Allowed for the rest of this job') ||
            result?.startsWith('No answer came in time') // (refused for them before it expired: never 'expired')
          ? result
          : '';
  // 'once', 'job' (this request now, and the rest of its kind for this job: the agent checks the kind), or 'deny'
  const choose = async (reply: 'once' | 'job' | 'deny') => {
    if (
      !approval ||
      !onReply ||
      locked.current ||
      result ||
      Date.now() >= approval.expires_at * 1000
    )
      return;
    locked.current = true;
    setSending(true);
    setError('');
    try {
      const words =
        reply === 'once' ? 'Allow once' : reply === 'job' ? 'Allow for this job' : 'Deny';
      await onReply(`${words} ${approval.code}`, approval.code);
    } catch {
      locked.current = false;
      setSending(false);
      setError('The reply was not sent. Try again.');
    }
  };
  return (
    <div data-worker-approval>
      <p className="[overflow-wrap:anywhere] whitespace-pre-wrap">{text}</p>
      {(settled || expired || result || error || sending) && (
        <p role="status" className="mt-2">
          {settled ||
            (expired ? 'This request expired. The Worker stopped.' : result || error || 'Sending…')}
        </p>
      )}
      {approval && !expired && !result && onReply && (
        <div className="mt-3 flex flex-wrap gap-2">
          {approval.choices.includes('allow_once') && (
            <Button
              type="button"
              className="min-h-11"
              disabled={sending}
              onClick={() => void choose('once')}
            >
              Allow
            </Button>
          )}
          {approval.choices.includes('allow_once') && approval.job_scope && (
            <Button
              type="button"
              variant="secondary"
              className="min-h-11"
              disabled={sending}
              onClick={() => void choose('job')}
            >
              Allow {approval.job_scope} for this job
            </Button>
          )}
          {approval.choices.includes('reject_once') && (
            <Button
              type="button"
              variant="secondary"
              className="min-h-11"
              disabled={sending}
              onClick={() => void choose('deny')}
            >
              Deny
            </Button>
          )}
        </div>
      )}
      {fullRequest && (
        <details className="text-muted-foreground mt-3">
          <summary className="cursor-pointer text-sm">Details</summary>
          <pre className="mt-2 text-xs [overflow-wrap:anywhere] whitespace-pre-wrap">
            {fullRequest}
          </pre>
        </details>
      )}
    </div>
  );
}
