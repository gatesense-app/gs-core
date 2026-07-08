// Shared style primitives. Colors reference CSS variables (see index.css) so
// everything re-themes when the data-theme attribute flips.
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
  input: {
    width: '100%', padding: '10px 14px', borderRadius: 8,
    border: '1px solid var(--c-border)', background: 'var(--c-input-bg)',
    color: 'var(--c-text)', fontSize: 14, marginBottom: 16, outline: 'none',
    boxSizing: 'border-box',
  },
  btn: {
    padding: '10px 18px', borderRadius: 8,
    background: 'linear-gradient(135deg, var(--c-accent), var(--c-accent-2))',
    border: 'none', color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer',
    boxShadow: '0 6px 16px -8px var(--c-accent)',
  },
  btnGhost: {
    padding: '8px 14px', borderRadius: 8, background: 'transparent',
    border: '1px solid var(--c-border)', color: 'var(--c-sub)', fontSize: 13, cursor: 'pointer',
  },
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
  x: { cursor: 'pointer', color: 'var(--c-muted)', fontWeight: 700, lineHeight: 1 },
}
