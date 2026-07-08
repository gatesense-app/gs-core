// Shared theme tokens + style primitives, matching the existing dark UI.
export const colors = {
  bg: '#0a0c12',
  panel: '#131620',
  border: '#1e2130',
  text: '#f1f5f9',
  sub: '#94a3b8',
  muted: '#64748b',
  accent: '#7c3aed',
  accentLight: '#a78bfa',
  error: '#f87171',
  ok: '#22c55e',
}

export const ui = {
  page: { maxWidth: 1000, margin: '32px auto', padding: '0 24px' },
  narrow: { maxWidth: 460, margin: '60px auto', padding: '0 20px' },
  h1: { fontSize: 22, fontWeight: 600, color: colors.text, marginBottom: 6 },
  sub: { fontSize: 14, color: colors.muted, marginBottom: 24 },
  row: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 },
  label: { display: 'block', fontSize: 13, color: colors.sub, marginBottom: 6 },
  input: {
    width: '100%', padding: '10px 14px', borderRadius: 8,
    border: `1px solid ${colors.border}`, background: colors.panel,
    color: '#e2e8f0', fontSize: 14, marginBottom: 16, outline: 'none',
    boxSizing: 'border-box',
  },
  btn: {
    padding: '10px 18px', borderRadius: 8, background: colors.accent,
    border: 'none', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer',
  },
  btnGhost: {
    padding: '8px 14px', borderRadius: 8, background: 'transparent',
    border: `1px solid ${colors.border}`, color: colors.sub, fontSize: 13, cursor: 'pointer',
  },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: {
    textAlign: 'left', fontSize: 12, color: colors.muted,
    padding: '0 12px 10px', borderBottom: `1px solid ${colors.border}`,
  },
  td: { padding: '12px', fontSize: 14, color: colors.text, borderBottom: '1px solid #0f1117', verticalAlign: 'top' },
  error: { color: colors.error, fontSize: 13, marginTop: 12 },
  card: {
    background: colors.panel, border: `1px solid ${colors.border}`,
    borderRadius: 12, padding: 20, marginBottom: 24,
  },
  chip: {
    display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12,
    padding: '3px 9px', borderRadius: 99, background: '#7c3aed22',
    color: colors.accentLight, border: '1px solid #7c3aed44',
    marginRight: 6, marginBottom: 6,
  },
  x: { cursor: 'pointer', color: colors.muted, fontWeight: 700, lineHeight: 1 },
}
