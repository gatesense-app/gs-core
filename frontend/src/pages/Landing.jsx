import { useState } from 'react'
import { Link } from 'react-router-dom'
import './Landing.css'

const AGENT_COLOR = { gate: '#4f46e5', delivery: '#059669', intercom: '#db2777' }

// ---------------------------------------------------------------------------
// Icons — inline SVG, 1.5px stroke, 24px grid. No emoji, no icon-font dep.
// ---------------------------------------------------------------------------
const icon = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' }

const IconShield = (p) => <svg {...icon} {...p}><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3z" /><path d="M9 12l2 2 4-4" /></svg>
const IconTruck = (p) => <svg {...icon} {...p}><path d="M3 7h11v8H3z" /><path d="M14 10h4l3 3v2h-7z" /><circle cx="7" cy="17.5" r="1.6" /><circle cx="17.5" cy="17.5" r="1.6" /></svg>
const IconChat = (p) => <svg {...icon} {...p}><path d="M4 5h16v11H8l-4 4V5z" /></svg>
const IconTrace = (p) => <svg {...icon} {...p}><circle cx="5" cy="6" r="1.6" /><circle cx="5" cy="12" r="1.6" /><circle cx="5" cy="18" r="1.6" /><path d="M9 6h11M9 12h11M9 18h11" /></svg>
const IconKiosk = (p) => <svg {...icon} {...p}><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 7h6M9 11h6M9 15h3" /></svg>
const IconGrid = (p) => <svg {...icon} {...p}><rect x="3" y="3" width="8" height="8" rx="1.5" /><rect x="13" y="3" width="8" height="8" rx="1.5" /><rect x="3" y="13" width="8" height="8" rx="1.5" /><rect x="13" y="13" width="8" height="8" rx="1.5" /></svg>
const IconBolt = (p) => <svg {...icon} {...p}><path d="M13 3L4 14h6l-1 7 9-11h-6l1-7z" /></svg>
const IconCheck = (p) => <svg {...icon} width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" {...p}><path d="M20 6L9 17l-5-5" /></svg>
const IconChevron = (p) => <svg {...icon} width={18} height={18} strokeWidth={2} {...p}><path d="M6 9l6 6 6-6" /></svg>
const IconMenu = (p) => <svg {...icon} strokeWidth={2} {...p}><path d="M4 6h16M4 12h16M4 18h16" /></svg>
const IconClose = (p) => <svg {...icon} strokeWidth={2} {...p}><path d="M6 6l12 12M18 6L6 18" /></svg>

const FEATURES = [
  { icon: IconShield, title: 'Instant gate decisions', body: 'Standing rules per flat are checked in real time — trusted visitors are auto-approved, blocklisted ones are turned away, before the guard even finishes typing.' },
  { icon: IconTruck, title: 'Delivery triage', body: 'A dedicated agent screens delivery and courier drop-offs for anomalies, clearing routine orders instantly and escalating only what looks off.' },
  { icon: IconChat, title: 'Resident intercom, automated', body: 'No standing rule? The intercom agent messages the resident directly, handles follow-up questions, and relays their decision back to the gate.' },
  { icon: IconTrace, title: 'Full decision trace', body: 'Every action, every tool call, every line of reasoning is logged per session — a complete, human-readable audit trail for every visitor.' },
  { icon: IconKiosk, title: 'Guard kiosk app', body: 'A dead-simple entry form for security staff — visitor name, flat, purpose — that kicks off the whole pipeline in one submit.' },
  { icon: IconGrid, title: 'Live ops dashboard', body: 'Every session, agent, and status update streams into one table your management committee can watch in real time.' },
]

const STEPS = [
  { agent: 'gate', title: 'Gate Agent', desc: 'Checks standing rules for the flat the instant a guard logs the visitor. Clear match → auto-approve or deny in under two seconds.' },
  { agent: 'delivery', title: 'Delivery Agent', desc: 'Ambiguous delivery or courier visits are triaged separately — routine orders clear automatically, odd ones get flagged.' },
  { agent: 'intercom', title: 'Intercom Agent', desc: 'Anything left unresolved goes straight to the resident as a conversation. No app install, no missed calls, just a decision.' },
]

const PLANS = [
  {
    name: 'Starter', price: '₹2,999', period: '/month', tag: 'Up to 150 flats',
    features: ['1 gate / entry point', 'Gate + Delivery agents', '90-day decision trace history', 'Email support'],
  },
  {
    name: 'Society', price: '₹7,999', period: '/month', tag: 'Up to 500 flats', popular: true,
    features: ['Unlimited gates', 'All three agents incl. Intercom', 'Unlimited decision trace history', 'WhatsApp resident notifications', 'Priority support'],
  },
  {
    name: 'Enterprise', price: 'Custom', period: '', tag: 'Multi-property portfolios',
    features: ['Everything in Society', 'Multi-property management console', 'SSO + audit export', 'Dedicated success manager'],
  },
]

const FAQS = [
  { q: 'Does this replace our security guards?', a: 'No — guards still staff the gate and log every visitor through the kiosk app. GateSense automates the approval decision behind that entry and keeps a full record of why each call was made.' },
  { q: "What happens if a resident doesn't reply?", a: "The intercom agent waits for a response, then falls back in order: the flat's backup contact, then the guard's default policy for that visit type — nobody is left standing at the gate." },
  { q: 'Can we set different rules per flat?', a: "Yes. Standing rules — trusted visitors, recurring deliveries, blocklists — are configured per flat and evaluated instantly by the Gate Agent before anything reaches a resident." },
  { q: 'Is every decision explainable?', a: 'Every session has a full decision trace: which agent acted, what it reasoned, which tools it called, and when. Nothing is a black box — your committee can review any entry after the fact.' },
  { q: 'Do residents need to install an app?', a: 'No. Notifications reach residents through the channel your society already uses (intercom, SMS, or WhatsApp) — there is nothing for residents to download or configure.' },
  { q: 'How fast are decisions actually made?', a: 'Standing-rule matches from the Gate or Delivery agent resolve in under two seconds. Only genuinely ambiguous visits are routed to a resident conversation.' },
]

function FaqItem({ q, a, open, onToggle }) {
  return (
    <div className={`faq-item${open ? ' faq-item--open' : ''}`}>
      <button className="faq-question" onClick={onToggle} aria-expanded={open}>
        <span>{q}</span>
        <IconChevron className="faq-chevron" />
      </button>
      {open && <div className="faq-answer">{a}</div>}
    </div>
  )
}

export default function Landing() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [openFaq, setOpenFaq] = useState(0)

  return (
    <div className="landing">
      <a href="#main" className="skip-link">Skip to content</a>

      <header className="lp-nav">
        <div className="lp-nav-inner">
          <Link to="/" className="lp-logo">GateSense</Link>

          <nav className="lp-nav-links" aria-label="Primary">
            <a href="#how-it-works">How it works</a>
            <a href="#features">Features</a>
            <a href="#pricing">Pricing</a>
            <a href="#faq">FAQ</a>
          </nav>

          <div className="lp-nav-actions">
            <Link to="/dashboard" className="lp-link-btn">Sign in</Link>
            <Link to="/kiosk" className="lp-btn lp-btn--primary">Get started</Link>
          </div>

          <button
            className="lp-nav-toggle"
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(o => !o)}
          >
            {menuOpen ? <IconClose /> : <IconMenu />}
          </button>
        </div>

        {menuOpen && (
          <div className="lp-nav-mobile">
            <a href="#how-it-works" onClick={() => setMenuOpen(false)}>How it works</a>
            <a href="#features" onClick={() => setMenuOpen(false)}>Features</a>
            <a href="#pricing" onClick={() => setMenuOpen(false)}>Pricing</a>
            <a href="#faq" onClick={() => setMenuOpen(false)}>FAQ</a>
            <Link to="/dashboard" onClick={() => setMenuOpen(false)}>Sign in</Link>
            <Link to="/kiosk" className="lp-btn lp-btn--primary" onClick={() => setMenuOpen(false)}>Get started</Link>
          </div>
        )}
      </header>

      <main id="main">
        {/* Hero */}
        <section className="lp-hero">
          <div className="lp-hero-copy">
            <div className="lp-eyebrow"><IconBolt width={14} height={14} /> Three-agent AI visitor pipeline</div>
            <h1>Visitor approvals that run themselves.</h1>
            <p className="lp-hero-sub">
              GateSense screens every guest, delivery, and service visit at your gate — approving the
              obvious ones instantly, triaging deliveries automatically, and looping in residents only
              when a real decision is needed. Every call is logged and explainable.
            </p>
            <div className="lp-hero-cta">
              <Link to="/kiosk" className="lp-btn lp-btn--primary lp-btn--lg">Start free trial</Link>
              <Link to="/dashboard" className="lp-btn lp-btn--ghost lp-btn--lg">View live dashboard</Link>
            </div>
            <div className="lp-hero-stats">
              <div><strong>&lt;2s</strong><span>avg. gate decision</span></div>
              <div><strong>3</strong><span>specialized AI agents</span></div>
              <div><strong>100%</strong><span>auditable trace</span></div>
            </div>
          </div>

          <div className="lp-hero-visual" aria-hidden="true">
            <div className="lp-mock-card">
              <div className="lp-mock-header">
                <span>Visitor Sessions</span>
                <span className="lp-mock-live"><i /> live</span>
              </div>
              {[
                { name: 'Raju · Swiggy delivery', flat: 'A-202', agents: ['gate', 'delivery'], status: 'auto_approved', label: 'Auto-approved' },
                { name: 'Meena Iyer · Guest', flat: 'B-104', agents: ['gate', 'intercom'], status: 'awaiting_resident', label: 'Awaiting resident' },
                { name: 'Unknown · Cab', flat: 'C-311', agents: ['gate'], status: 'denied', label: 'Denied' },
              ].map((row) => (
                <div className="lp-mock-row" key={row.name}>
                  <div className="lp-mock-row-main">
                    <span className="lp-mock-name">{row.name}</span>
                    <span className="lp-mock-flat">{row.flat}</span>
                  </div>
                  <div className="lp-mock-row-meta">
                    <div className="lp-mock-chips">
                      {row.agents.map(a => (
                        <span key={a} className="lp-mock-chip" style={{ background: AGENT_COLOR[a] + '22', color: AGENT_COLOR[a] }}>{a}</span>
                      ))}
                    </div>
                    <span className={`lp-mock-status lp-mock-status--${row.status}`}>{row.label}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Logos / trust strip */}
        <section className="lp-strip">
          <span>Built for gated communities &amp; residential societies</span>
          <div className="lp-strip-divider" />
          <span>Works alongside the security guards you already have</span>
        </section>

        {/* How it works */}
        <section className="lp-section" id="how-it-works">
          <div className="lp-section-head">
            <h2>One entry, three agents, zero manual approvals</h2>
            <p>Each visitor session flows through a pipeline built for real gate conditions — fast where it can be, careful where it must be.</p>
          </div>

          <div className="lp-steps">
            {STEPS.map((step, i) => (
              <div className="lp-step" key={step.agent}>
                <div className="lp-step-num" style={{ color: AGENT_COLOR[step.agent], borderColor: AGENT_COLOR[step.agent] + '55' }}>{i + 1}</div>
                <div className="lp-step-title" style={{ color: AGENT_COLOR[step.agent] }}>{step.title}</div>
                <p>{step.desc}</p>
                {i < STEPS.length - 1 && <div className="lp-step-connector" aria-hidden="true" />}
              </div>
            ))}
          </div>
        </section>

        {/* Features */}
        <section className="lp-section lp-section--muted" id="features">
          <div className="lp-section-head">
            <h2>Everything the gate needs, nothing residents notice</h2>
            <p>A focused feature set built around one job: getting the right visitors through, fast, with a record you can trust.</p>
          </div>

          <div className="lp-features">
            {FEATURES.map(f => (
              <div className="lp-feature-card" key={f.title}>
                <div className="lp-feature-icon"><f.icon /></div>
                <div className="lp-feature-title">{f.title}</div>
                <p>{f.body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Pricing */}
        <section className="lp-section" id="pricing">
          <div className="lp-section-head">
            <h2>Simple pricing, per society</h2>
            <p>Every plan includes the full decision-trace audit log. Upgrade as your community grows.</p>
          </div>

          <div className="lp-pricing">
            {PLANS.map(plan => (
              <div className={`lp-plan${plan.popular ? ' lp-plan--popular' : ''}`} key={plan.name}>
                {plan.popular && <div className="lp-plan-badge">Most popular</div>}
                <div className="lp-plan-name">{plan.name}</div>
                <div className="lp-plan-price">{plan.price}<span>{plan.period}</span></div>
                <div className="lp-plan-tag">{plan.tag}</div>
                <ul className="lp-plan-features">
                  {plan.features.map(f => (
                    <li key={f}><IconCheck className="lp-plan-check" />{f}</li>
                  ))}
                </ul>
                <Link to="/kiosk" className={`lp-btn ${plan.popular ? 'lp-btn--primary' : 'lp-btn--ghost'} lp-plan-cta`}>
                  {plan.price === 'Custom' ? 'Contact sales' : 'Start free trial'}
                </Link>
              </div>
            ))}
          </div>
        </section>

        {/* FAQ */}
        <section className="lp-section lp-section--muted lp-section--narrow" id="faq">
          <div className="lp-section-head">
            <h2>Frequently asked questions</h2>
          </div>
          <div className="lp-faq">
            {FAQS.map((f, i) => (
              <FaqItem key={f.q} q={f.q} a={f.a} open={openFaq === i} onToggle={() => setOpenFaq(openFaq === i ? -1 : i)} />
            ))}
          </div>
        </section>

        {/* Final CTA */}
        <section className="lp-cta">
          <h2>Stop approving every visitor by hand.</h2>
          <p>Set up your first gate in minutes — no hardware changes, no resident app required.</p>
          <Link to="/kiosk" className="lp-btn lp-btn--primary lp-btn--lg">Start free trial</Link>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-footer-inner">
          <div>
            <div className="lp-logo">GateSense</div>
            <p>AI visitor management for gated communities.</p>
          </div>
          <div className="lp-footer-links">
            <div>
              <div className="lp-footer-heading">Product</div>
              <a href="#how-it-works">How it works</a>
              <a href="#features">Features</a>
              <a href="#pricing">Pricing</a>
            </div>
            <div>
              <div className="lp-footer-heading">App</div>
              <Link to="/kiosk">Guard kiosk</Link>
              <Link to="/dashboard">Dashboard</Link>
            </div>
          </div>
        </div>
        <div className="lp-footer-bottom">© {new Date().getFullYear()} GateSense. All rights reserved.</div>
      </footer>
    </div>
  )
}
