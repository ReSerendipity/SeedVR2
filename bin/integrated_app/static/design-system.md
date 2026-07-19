# SeedVR2 Design System

## CSS Custom Properties (Tokens)

### Color Tokens

#### Primary & Accent

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--sv-primary` | `#9b8ec4` | `#7c6fad` | Primary actions, links, focus rings |
| `--sv-primary-hover` | `#b0a4d4` | `#8d80be` | Primary button hover state |
| `--sv-primary-active` | `#8a7db5` | `#6d60a0` | Primary button active/pressed state |
| `--sv-primary-dim` | `rgba(155,142,196,0.18)` | `rgba(124,111,173,0.12)` | Backgrounds, badges, subtle highlights |
| `--sv-primary-glow` | `rgba(155,142,196,0.35)` | `rgba(124,111,173,0.2)` | Glow effects, brand icon shadow |
| `--sv-accent-purple` | `#b8a9d4` | `#6b5e9c` | Secondary accent, hero gradient (薰衣草统一) |
| `--sv-accent-purple-dim` | `rgba(184,169,212,0.18)` | `rgba(107,94,156,0.12)` | Purple accent backgrounds |
| `--sv-accent-pink` | `#c4a9d4` | `#8a6fad` | Tertiary accent, hero gradient (薰衣草统一) |
| `--sv-accent-pink-dim` | `rgba(196,169,212,0.18)` | `rgba(138,111,173,0.12)` | Pink accent backgrounds |

#### Semantic Colors

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--sv-success` | `#34d399` | `#15803d` | Success states, completed badges |
| `--sv-success-dim` | `rgba(52,211,153,0.18)` | `rgba(21,128,61,0.12)` | Success backgrounds |
| `--sv-success-hover` | `#6ee7b7` | `#16a34a` | Success interactive hover |
| `--sv-warning` | `#fbbf24` | `#b45309` | Warning states, caution indicators |
| `--sv-warning-dim` | `rgba(251,191,36,0.18)` | `rgba(180,83,9,0.12)` | Warning backgrounds |
| `--sv-warning-hover` | `#fcd34d` | `#d97706` | Warning interactive hover |
| `--sv-danger` | `#f87171` | `#dc2626` | Error states, delete actions |
| `--sv-danger-dim` | `rgba(248,113,113,0.18)` | `rgba(220,38,38,0.12)` | Danger backgrounds |
| `--sv-danger-hover` | `#fca5a5` | `#ef4444` | Danger interactive hover |
| `--sv-info` | `#60a5fa` | `#1d4ed8` | Informational states, links |
| `--sv-info-dim` | `rgba(96,165,250,0.18)` | `rgba(29,78,216,0.12)` | Info backgrounds |
| `--sv-info-hover` | `#93c5fd` | `#2563eb` | Info interactive hover |

#### Background Tokens

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--sv-bg-base` | `#0f1117` | `#f8fafc` | Page background |
| `--sv-bg-surface` | `#161822` | `#ffffff` | Card surfaces |
| `--sv-bg-elevated` | `#1e2030` | `#f1f5f9` | Elevated elements, dropdowns |
| `--sv-bg-overlay` | `#252840` | `#e2e8f0` | Overlays, disabled tracks |
| `--sv-bg-hover` | `#2a2d45` | `#e2e8f0` | Hover backgrounds |

#### Border Tokens

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--sv-border` | `rgba(255,255,255,0.06)` | `rgba(0,0,0,0.08)` | Default borders |
| `--sv-border-hover` | `rgba(255,255,255,0.12)` | `rgba(0,0,0,0.15)` | Hover borders |
| `--sv-border-focus` | `var(--sv-primary)` | `var(--sv-primary)` | Focus ring color |

#### Text Tokens

| Token | Dark | Light | Usage |
|-------|------|-------|-------|
| `--sv-text-primary` | `#e2e8f0` | `#1e293b` | Headings, body text |
| `--sv-text-secondary` | `#94a3b8` | `#475569` | Secondary descriptions |
| `--sv-text-muted` | `#94a3b8` | `#546478` | Hints, placeholders, metadata |
| `--sv-text-inverse` | `#0f1117` | `#ffffff` | Text on primary-colored backgrounds |

#### Shadow Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--sv-shadow-sm` | Dark: `0 1px 3px rgba(0,0,0,0.3)` / Light: `0 1px 3px rgba(0,0,0,0.08)` | Subtle elevation |
| `--sv-shadow` | Dark: `0 4px 12px rgba(0,0,0,0.4)` / Light: `0 4px 12px rgba(0,0,0,0.1)` | Cards, dropdowns |
| `--sv-shadow-lg` | Dark: `0 8px 30px rgba(0,0,0,0.5)` / Light: `0 8px 30px rgba(0,0,0,0.12)` | Modals, toasts |
| `--sv-shadow-glow` | `0 0 20px var(--sv-primary-glow)` | Brand icon, focused elements |

### Spacing Tokens (4px base)

| Token | Value |
|-------|-------|
| `--sv-space-1` | `4px` |
| `--sv-space-1-5` | `6px` |
| `--sv-space-2` | `8px` |
| `--sv-space-2-5` | `10px` |
| `--sv-space-3` | `12px` |
| `--sv-space-4` | `16px` |
| `--sv-space-5` | `20px` |
| `--sv-space-6` | `24px` |
| `--sv-space-7` | `32px` |
| `--sv-space-8` | `40px` |
| `--sv-space-9` | `48px` |

### Radius Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--sv-radius-sm` | `6px` | Small elements, badges, inputs |
| `--sv-radius` | `10px` | Cards, buttons, form controls |
| `--sv-radius-lg` | `14px` | Large cards, modals |
| `--sv-radius-xl` | `20px` | Hero elements, feature sections |

### Typography

- **Font Family:** `"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif`
- **Line Height:** `1.6`
- **Hero Title:** `2.25rem`, weight `800`, letter-spacing `-0.03em`
- **Page Title:** `1.2rem` (via `.sv-text-lg`)
- **Body:** `0.85rem` (via `.sv-text-sm`)
- **Small:** `0.75rem` (via `.sv-text-xs`)

### Animation & Transition Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--sv-easing-standard` | `cubic-bezier(0.4, 0, 0.2, 1)` | Standard transitions |
| `--sv-easing-decelerate` | `cubic-bezier(0, 0, 0.2, 1)` | Enter animations |
| `--sv-easing-accelerate` | `cubic-bezier(0.4, 0, 1, 1)` | Exit animations |
| `--sv-easing-bounce` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Bounce effects |
| `--sv-transition` | `0.2s var(--sv-easing-standard)` | Default transition |
| `--sv-transition-slow` | `0.35s var(--sv-easing-standard)` | Slow transitions (theme switch) |

### Layout Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--sv-navbar-height` | `56px` | Top navigation bar height |
| `--sv-statusbar-height` | `32px` | Bottom status bar height |

## Responsive Breakpoints

| Breakpoint | Value | Key Changes |
|------------|-------|-------------|
| Mobile (XS) | `max-width: 576px` | Single column grids, stacked layouts |
| Tablet | `max-width: 768px` | Hidden desktop nav, mobile card views |
| Desktop (MD) | `max-width: 992px` | Single column restore layout, 2-col quick cards |
| Large | `min-width: 1600px` | Wider restore params, 4-col status grid |

## Component Guidelines

### Cards (`.sv-card`)
- Use `--sv-bg-surface` background with `--sv-border` border
- Apply `--sv-radius-lg` border radius
- Header uses `font-weight: 600` with icon prefix
- Hover state: `border-color: var(--sv-border-hover)`

### Buttons (`.sv-btn`)
- Variants: `sv-btn-primary`, `sv-btn-secondary`, `sv-btn-outline`, `sv-btn-danger`
- Sizes: default, `sv-btn-sm`, `sv-btn-icon`
- Use `--sv-transition` for hover/active states
- Icon buttons: 32px square with centered icon

### Badges (`.sv-badge`)
- Variants: `sv-badge-pending`, `sv-badge-processing`, `sv-badge-completed`, `sv-badge-failed`, `sv-badge-secondary`
- Small inline status indicators with semantic colors

### Forms (`.sv-form-control`)
- Use `--sv-bg-elevated` background
- Border: `1px solid var(--sv-border)`
- Focus: `border-color: var(--sv-border-focus)` with glow
- Validation error: red border + `.sv-form-error` message

### Toast Notifications (`.sv-toast`)
- Fixed position, bottom-right
- Max 3 visible at once
- Auto-dismiss after 4 seconds
- Types: success, error, warning, info

### Progress Bars (`.sv-progress`)
- Track: `--sv-bg-overlay` background, `6px` height
- Fill: primary color with transition animation
- Animated variant: striped animation for in-progress

## Accessibility

- **Skip Link:** `.sv-skip-link` for keyboard navigation
- **Focus Visible:** All interactive elements have visible focus rings
- **ARIA:** Roles, labels, and states on interactive components
- **Reduced Motion:** `@media (prefers-reduced-motion: reduce)` disables animations
- **Color Contrast:** Text tokens meet WCAG AA contrast requirements
