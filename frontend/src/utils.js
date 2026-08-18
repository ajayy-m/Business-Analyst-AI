/**
 * The synthesis prompts explicitly tell the model not to use markdown,
 * but LLMs don't always perfectly follow formatting instructions. This
 * is a safety net -- strips the common cases (bold, headers, bullets)
 * so a stray "**Product B**" renders as "Product B" instead of literal
 * asterisks, rather than the UI depending entirely on prompt compliance.
 */
export function stripMarkdown(text) {
  if (!text) return text;
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1') // **bold**
    .replace(/\*(.+?)\*/g, '$1')     // *italic*
    .replace(/^#{1,6}\s+/gm, '')     // # headers
    .replace(/^[-*]\s+/gm, '');      // - bullets
}