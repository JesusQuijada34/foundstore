## Design System: Foundstore

### Pattern
- **Name:** App Store Style Landing
- **Conversion Focus:** Show real screenshots. Include ratings (4.5+ stars). QR code for mobile. Platform-specific CTAs.
- **CTA Placement:** Download buttons prominent (App Store + Play Store) throughout
- **Color Strategy:** Dark/light matching app store feel. Star ratings in gold. Screenshots with device frames.
- **Sections:** 1. Hero with device mockup, 2. Screenshots carousel, 3. Features with icons, 4. Reviews/ratings, 5. Download CTAs

### Style
- **Name:** Dark Mode (OLED)
- **Mode Support:** Light ✗ No | Dark ✓ Only
- **Keywords:** Dark theme, low light, high contrast, deep black, midnight blue, eye-friendly, OLED, night mode, power efficient
- **Best For:** Night-mode apps, coding platforms, entertainment, eye-strain prevention, OLED devices, low-light
- **Performance:** ⚡ Excellent | **Accessibility:** ✓ WCAG AAA

### Colors
| Role | Hex | CSS Variable |
|------|-----|--------------|
| Primary | `#1E293B` | `--color-primary` |
| On Primary | `#FFFFFF` | `--color-on-primary` |
| Secondary | `#334155` | `--color-secondary` |
| Accent/CTA | `#22C55E` | `--color-accent` |
| Background | `#0F172A` | `--color-background` |
| Foreground | `#F8FAFC` | `--color-foreground` |
| Muted | `#272F42` | `--color-muted` |
| Border | `#475569` | `--color-border` |
| Destructive | `#EF4444` | `--color-destructive` |
| Ring | `#1E293B` | `--color-ring` |

*Notes: Code dark + run green*

### Typography
- **Heading:** Inter
- **Body:** Inter
- **Mood:** dark, cinematic, technical, precision, clean, premium, developer, professional, high-end utility
- **Best For:** Developer tools, fintech/trading, AI dashboards, streaming platforms, high-end productivity apps
- **Google Fonts:** https://fonts.google.com/share?selection.family=Inter:wght@300;400;500;600;700
- **CSS Import:**
```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
```

### Key Effects
Minimal glow (text-shadow: 0 0 10px), dark-to-light transitions, low white emission, high readability, visible focus

### Avoid (Anti-patterns)
- Light mode default
- Slow performance

### Pre-Delivery Checklist
- [ ] No emojis as icons (use SVG: Heroicons/Lucide)
- [ ] cursor-pointer on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Light mode: text contrast 4.5:1 minimum
- [ ] Focus states visible for keyboard nav
- [ ] prefers-reduced-motion respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px

