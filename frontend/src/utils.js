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

/**
 * Turns an uploaded filename into a safe backend table name, e.g.
 * "Q3 Sales Data (final).xlsx" -> "q3_sales_data_final". The user never
 * sees or types this -- it only exists so DuckDB has something legal to
 * call the table.
 */
export function slugify(filename) {
  const base = filename.replace(/\.[^./]+$/, ''); // strip extension
  const slug = base
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return slug || 'data';
}

/**
 * Reverses slugify for display, e.g. "q3_sales_data_final" -> "Q3 Sales
 * Data Final". Used anywhere a table name would otherwise leak backend
 * naming into the UI.
 */
export function humanize(slug) {
  if (!slug) return slug;
  return slug
    .split(/[_-]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

/**
 * The backend still needs a dataset_id to namespace tables, but the
 * person should never see or manage it. We generate one silently on
 * first visit and persist it in localStorage, so the same browser
 * always comes back to the same workspace of uploaded data.
 */
const WORKSPACE_KEY = 'aiba_workspace_id';

export function getWorkspaceId() {
  let id = localStorage.getItem(WORKSPACE_KEY);
  if (!id) {
    id = `ws_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    localStorage.setItem(WORKSPACE_KEY, id);
  }
  return id;
}

/**
 * Clears the current workspace pointer (e.g. a "Start over" action).
 * Does not delete the underlying data on the backend -- just forgets
 * which dataset_id this browser was pointed at, so a fresh one gets
 * generated on next load.
 */
export function resetWorkspace() {
  localStorage.removeItem(WORKSPACE_KEY);
}

/**
 * Because DuckDB uploads do `CREATE OR REPLACE TABLE`, uploading two
 * files that slugify to the same name would silently overwrite the
 * first one's data with no warning to a non-technical user. This picks
 * a safe, unique name (sales, sales_2, sales_3, ...) against whatever
 * table names already exist in the catalog.
 */
export function uniqueTableName(filename, existingNames = []) {
  const base = slugify(filename);
  const taken = new Set(existingNames);
  if (!taken.has(base)) return base;
  let i = 2;
  while (taken.has(`${base}_${i}`)) i += 1;
  return `${base}_${i}`;
}