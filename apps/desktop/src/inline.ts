/** The small piece of Markdown the app renders inside a line: **bold**, `code` and _italic_. */
export type InlinePart = { kind: 'text' | 'bold' | 'code' | 'italic'; text: string }

// An underscore only opens or closes italics at a word boundary, so snake_case names and URLs stay whole.
const MARKUP = /(\*\*[^*]+\*\*|`[^`]+`|(?<!\w)_[^_\s][^_]*_(?!\w))/g

export function inlineParts(text: string): InlinePart[] {
  // split() with one capture group puts plain text at even indexes and the matched markup at odd ones.
  return text.split(MARKUP).flatMap((part, i): InlinePart[] => {
    if (i % 2 === 0) return part ? [{ kind: 'text', text: part }] : []
    if (part.startsWith('**')) return [{ kind: 'bold', text: part.slice(2, -2) }]
    if (part.startsWith('`')) return [{ kind: 'code', text: part.slice(1, -1) }]
    return [{ kind: 'italic', text: part.slice(1, -1) }]
  })
}
