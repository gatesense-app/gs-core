// Shared style primitives.
//
// Buttons and inputs are NOT here — they're CSS classes in index.css (.btn,
// .input), because :hover / :focus-visible / :disabled can't be expressed in
// inline styles, which is why the app had none of them. Use:
//   <button className="btn btn--primary">      (see index.css for variants)
//   <input className="input" />
// Inline styles beat CSS classes, so don't re-add style={ui.btn} on top.
export const colors = {
  bg: 'var(--c-bg)',
  panel: 'var(--c-panel)',
  border: 'var(--c-border)',
  text: 'var(--c-text)',
  sub: 'var(--c-sub)',
  muted: 'var(--c-muted)',
  accent: 'var(--c-accent)',
  accentLight: 'var(--c-accent-soft)',
  error: 'var(--c-error)',
  ok: 'var(--c-ok)',
}

export const ui = {
  page: { maxWidth: 1000, margin: '32px auto', padding: '0 24px' },
  narrow: { maxWidth: 460, margin: '60px auto', padding: '0 20px' },
  h1: { fontSize: 22, fontWeight: 700, color: 'var(--c-text)', marginBottom: 6, letterSpacing: '-0.01em' },
  sub: { fontSize: 14, color: 'var(--c-muted)', marginBottom: 24 },
  row: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 },
  label: { display: 'block', fontSize: 13, color: 'var(--c-sub)', marginBottom: 6 },
  // Spacing-only helper for stacked form fields; the look comes from .input.
  fieldGap: { marginBottom: 16 },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: {
    textAlign: 'left', fontSize: 12, color: 'var(--c-muted)',
    padding: '0 12px 10px', borderBottom: '1px solid var(--c-border)',
  },
  td: { padding: '12px', fontSize: 14, color: 'var(--c-text)', borderBottom: '1px solid var(--c-row-border)', verticalAlign: 'top' },
  error: { color: 'var(--c-error)', fontSize: 13, marginTop: 12 },
  card: {
    background: 'var(--c-panel)', border: '1px solid var(--c-border)',
    borderRadius: 12, padding: 20, marginBottom: 24, boxShadow: 'var(--c-card-shadow)',
  },
  chip: {
    display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12,
    padding: '3px 9px', borderRadius: 99, background: 'var(--c-accent-bg)',
    color: 'var(--c-accent-soft)', border: '1px solid var(--c-accent-border)',
    marginRight: 6, marginBottom: 6,
  },
}
