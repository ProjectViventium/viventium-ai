// Her numbered lines keep their numbers as words on the page. Markdown reads a line that begins "1363. " as item 1363 of
// a numbered list, and the browser then draws that number as a list marker: it shows, but it is not text, so copying
// her reply, reading the page's text, or a screen reader's text drops it ("1363. The math finally clocked in"
// read as "The math finally clocked in"). Each numbered item is given its number as its first words, as she wrote it,
// and the list is drawn without markers, so what is seen is what is there.
type MarkdownNode = {
  type: string;
  value?: string;
  ordered?: boolean | null;
  start?: number | null;
  children?: MarkdownNode[];
  data?: { hProperties?: Record<string, unknown> } & Record<string, unknown>;
};

export function numbersAsText() {
  const visit = (node: MarkdownNode) => {
    for (const child of node.children ?? []) visit(child);
    if (node.type !== 'list' || !node.ordered) return;
    let n = typeof node.start === 'number' ? node.start : 1;
    for (const item of node.children ?? []) {
      if (item.type !== 'listItem') continue;
      const words: MarkdownNode = { type: 'text', value: `${n}. ` };
      n += 1;
      const first = item.children?.[0];
      if (first?.type === 'paragraph') first.children = [words, ...(first.children ?? [])];
      else item.children = [{ type: 'paragraph', children: [words] }, ...(item.children ?? [])];
    }
    node.ordered = false;
    node.start = null;
    const props = node.data?.hProperties ?? {};
    const had = props.className;
    const classes = Array.isArray(had) ? had : typeof had === 'string' ? [had] : [];
    node.data = { ...node.data, hProperties: { ...props, className: [...classes, 'list-none'] } };
  };
  return (tree: MarkdownNode) => visit(tree);
}
