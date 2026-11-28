// Each file she offers, shown once where her words carry it. Telling a Worker's result, her agent offers its file first
// (call/agent.py show_file: a row that is only the file's link, as core/attachments.py link() writes it), and then she
// tells the result; when her words carry the same file's link (a model copies it from the result), the page showed it
// twice, live and again from her record (release 59, a real user's run). Decided on the offer row's exact form and the
// file's id, never on her words: what she wrote and the record stay exactly as they are.

// (an offer row: one link to a file of hers, nothing else; its label as link() escapes it)
const OFFER = /^\[(?:\\.|[^\\[\]\n])*\]\(#viv-file-([a-f0-9]{32})\)$/;
// (her code, where a link is her literal text, not a link)
const CODE = /```[\s\S]*?(?:```|$)|`[^`\n]*`/g;

type Said = { message: string; from?: { isLocal?: boolean } };

/** The messages as shown: an offer row is left out when a later message of hers, before his next one, links the same
 *  file outside code (her words carry it). An offer she does not repeat stays, as does every other message. */
export function offeredOnce<T extends Said>(messages: T[]): T[] {
  return messages.filter((said, n) => {
    if (said.from?.isLocal) return true;
    const id = OFFER.exec(said.message?.trim() ?? '')?.[1];
    if (!id) return true;
    for (const later of messages.slice(n + 1)) {
      if (later.from?.isLocal) return true;
      if ((later.message ?? '').replace(CODE, '').includes(`](#viv-file-${id})`)) return false;
    }
    return true;
  });
}
