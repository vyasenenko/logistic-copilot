---
name: Marketing landing page
overview: Replace HeroLogin on `/` with decision-complete B2B marketing landing for brokers/dispatch — dual CTA (anchor Sign In + mailto Book Demo), single LoginPanel, delete HeroLogin, CONTACT_EMAIL in publicContact.ts.
todos:
  - id: public-contact
    content: Create publicContact.ts (CONTACT_EMAIL + bookDemoMailtoUrl)
    status: completed
  - id: extract-login-panel
    content: Extract LoginPanel from HeroLogin; parent owns hasSession
    status: completed
  - id: landing-cta
    content: Add LandingProductCta — shared Sign In / Continue rules for all chrome CTAs
    status: completed
  - id: landing-content
    content: landing-content.ts — copy + mandatory FAQ (3 items)
    status: completed
  - id: marketing-landing-ui
    content: MarketingLanding.tsx — sections, one
    status: completed
  - id: wire-and-delete
    content: page.tsx thin entry; delete HeroLogin.tsx
    status: completed
  - id: qa
    content: Test anchor CTAs, session consistency, mailto, auth regressions
    status: completed
isProject: false
---

# Logistic Copilot — Marketing landing with integrated login

## Summary

Replace [`HeroLogin`](frontend/src/components/HeroLogin.tsx) on `/` with a **landing-first** page for **freight brokers / dispatch teams**. **Embedded login** unchanged. **Dual CTA:** Sign In (in-page anchor) + Book Demo (`mailto:`).

**Boundaries:** No changes to `/dashboard`, `/extension/login`, auth API, token storage, Turnstile, `AuthGate`. No new backend. English copy only.

## Locked implementation decisions

### 1. Sign In CTA mechanism (single model)

Use **native in-page anchors only** — no `scrollIntoView`, no custom scroll JS.

| Rule | Detail |
|------|--------|
| Target | Exactly one wrapper: `<section id="sign-in">` around the only `LoginPanel` instance |
| Links | All product Sign In CTAs render `<a href="#sign-in">` when user has no session |
| Smooth scroll | Add `scroll-behavior: smooth` on `html` in [`globals.css`](frontend/src/app/globals.css) (respect `prefers-reduced-motion: reduce` → `auto`) |
| Hero layout | On `lg+`, hero grid places the **`#sign-in` column in the right column** (same DOM node, not a duplicate form). On mobile, hero copy stacks above `#sign-in` |
| Final CTA band | Same `<a href="#sign-in">` — scrolls to the same panel (no second login mount) |

### 2. Session-aware CTA (consistent everywhere)

`MarketingLanding` performs **one** session check (same logic as today’s `HeroLogin` `useEffect` → `hasSession`). Pass `hasSession` into chrome CTAs.

**Component:** [`LandingProductCta.tsx`](frontend/src/components/landing/LandingProductCta.tsx) — used in **sticky header**, **hero** (under headline), **final CTA band**.

| `hasSession` | `LandingProductCta` renders |
|--------------|----------------------------|
| `false` | `<a href="#sign-in">Sign In</a>` (styled button) |
| `true` | `<button type="button" onClick={() => router.push('/dashboard')}>` **Continue to dashboard** |

**Book Demo** is always a plain `<a href={bookDemoMailtoUrl()}>` — never changes with session.

**`LoginPanel`** keeps its **internal** continue vs form UI (unchanged); does not drive header/footer labels.

### 3. Static vs session-aware sections

| Section | Static copy only | Uses `hasSession` |
|---------|------------------|-------------------|
| Sticky header | nav anchors | `LandingProductCta` + Book Demo |
| Hero (text column) | headline, subcopy, pills | `LandingProductCta` + Book Demo |
| Hero (`#sign-in` column) | — | `LoginPanel` only |
| Pain / value strip | yes | no |
| Core workflow | yes | no |
| Feature grid | yes | no |
| Trust / ops | yes | no |
| Integrations | yes | no |
| FAQ (mandatory) | yes | no |
| Final CTA band | supporting line | `LandingProductCta` + Book Demo |
| Footer | links, copyright | no |

### 4. Contact email location

**File:** [`frontend/src/constants/publicContact.ts`](frontend/src/constants/publicContact.ts) (new; do not put email in `brand.ts`).

```ts
export const DEFAULT_CONTACT_EMAIL = "vyasenenko@logisticopilot.com";

export function getContactEmail(): string {
  return (process.env.NEXT_PUBLIC_CONTACT_EMAIL || "").trim() || DEFAULT_CONTACT_EMAIL;
}

export function bookDemoMailtoUrl(): string {
  const subject = encodeURIComponent("Logistic Copilot demo request");
  return `mailto:${getContactEmail()}?subject=${subject}`;
}
```

[`brand.ts`](frontend/src/constants/brand.ts) stays **product name only** (`PRODUCT_DISPLAY_NAME`).

### 5. HeroLogin fate

**Delete** [`frontend/src/components/HeroLogin.tsx`](frontend/src/components/HeroLogin.tsx) after migration.

- Only consumer today: [`page.tsx`](frontend/src/app/page.tsx) — switch to `MarketingLanding`.
- **No** re-export, **no** deprecated wrapper, **no** thin alias.

### 6. FAQ

**Mandatory** section **#8** in page order (after Integrations, before Final CTA band). Exactly **3** items in `landing-content.ts`:

1. **Access** — workspace is invite-based; link to [`/invite`](frontend/src/app/invite/page.tsx) for token acceptance.
2. **Outlook** — mailbox connect is configured after sign-in (org admin / settings); no fake “connect on landing” flow.
3. **Automation** — AI proposes actions; operators approve, edit, or block at review gates (human-in-the-loop).

**Layout (locked):** **stacked Q/A cards** — no accordion, no expand/collapse state. Each item is a static card: question as `h3`/label on top, answer paragraph below, `space-y-3` between cards. Renders from `landing-content.ts` via `.map()`.

## Page structure (section order)

1. Sticky header — logo, `#workflow`, `#features`, `#faq`, `LandingProductCta`, Book Demo  
2. Hero — copy + dual CTA + right column = `#sign-in` / `LoginPanel`  
3. Pain / value strip (static)  
4. Core workflow (static)  
5. Feature grid (static)  
6. Trust / ops (static)  
7. Integrations — Outlook, documents, TMS (static)  
8. **FAQ** (static, mandatory, 3 items)  
9. Final CTA band — `LandingProductCta` + Book Demo  
10. Footer — Privacy Policy, `mailto:` contact, copyright  

## Messaging (English — brokers / dispatch)

- Outlook inbox as the operating layer for freight workflows  
- Quote intake, parsing, carrier outreach, bids, customer quote, booking/TMS, documents, status ops  
- Pillars: speed, less manual work, operator control, centralized visibility  
- Tone: B2B freight ops product, not generic AI startup  

## File map

| File | Action |
|------|--------|
| `frontend/src/constants/publicContact.ts` | **Create** |
| `frontend/src/components/landing/LoginPanel.tsx` | **Create** — extract auth from HeroLogin |
| `frontend/src/components/landing/LandingProductCta.tsx` | **Create** — session-aware Sign In / Continue |
| `frontend/src/components/landing/landing-content.ts` | **Create** — all marketing + FAQ copy |
| `frontend/src/components/landing/MarketingLanding.tsx` | **Create** — layout, `hasSession`, sections |
| `frontend/src/app/page.tsx` | **Update** — metadata + `<MarketingLanding />` |
| `frontend/src/components/HeroLogin.tsx` | **Delete** |
| `frontend/src/app/globals.css` | **Update** — `scroll-behavior` on `html` |

## Auth code to preserve (LoginPanel)

Move verbatim from `HeroLogin`:

- `AUTH_TOKEN_KEY`, `readLoginError`, Turnstile effect, `handleLogin`, `?next=` redirect  
- Submit disabled when Turnstile required and token empty  

## Metadata

`page.tsx`:

- `title`: `Logistic Copilot | AI Logistics Workflow`  
- `description`: Outlook-first AI workflow for brokers and dispatch — quote intake, bids, documents, TMS, operator control  

## Test plan

- `/` is full marketing landing  
- **Sign In** in header, hero, final band: all use `href="#sign-in"` when logged out; all show **Continue to dashboard** when `hasSession`  
- Clicking Sign In scrolls to single login form (desktop + mobile)  
- **Book Demo** → `bookDemoMailtoUrl()` with env override  
- Login, Turnstile, `?next=`, session continue — unchanged  
- No regressions: `/dashboard`, `/extension/login`, `/invite`  
- FAQ section (#8) present with 3 stacked Q/A cards (no accordion)  

## Out of scope (v1)

Signup, demo form, CRM, i18n, CMS, auth route changes, second login mount, `scrollIntoView` JS

## Success criteria

- Plan is **decision-complete** — no `or` / `optional` / `remove or re-export` left for implementer  
- Consistent session CTAs across header, hero, final band  
- `HeroLogin` removed; `publicContact.ts` owns sales email  
