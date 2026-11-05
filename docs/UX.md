# UX Guide — Local Vision Studio (working title)

Binding design rules for every screen. Source: the principles of Apple's Human Interface Guidelines (HIG), applied to a local web app. We follow the *principles*; we do **not** use Apple's SF fonts, SF Symbols, logos or name. A screen that fails the checklist at the end does not ship (Development Rule UX-1).

## 1. Principles
1. **Content first (clarity, deference).** Images and annotations are the product. Chrome stays quiet: low-contrast borders, no decorative gradients, controls appear where the work is.
2. **Direct manipulation.** Draw, drag, resize and delete on the image itself. Forms are for settings, not for annotation.
3. **Instant feedback.** Every action responds within 100 ms (hover, press, selection). Anything longer than 1 s shows progress; anything longer than 10 s shows progress, an estimate and a cancel button.
4. **Forgiveness.** Everything in the annotator is undoable (unlimited undo/redo). Prefer undo over "Are you sure?". Confirm only irreversible actions (delete dataset, delete run), naming exactly what is lost.
5. **Consistency.** Same layout everywhere: sidebar (navigation) · toolbar (actions) · canvas/list (content) · inspector (details). Same shortcut means the same thing on every screen.
6. **Progressive disclosure.** Defaults are right for a first run. Advanced training and hardware options sit behind "Advanced". Never ask a question the app can answer itself (detect GPU, pick batch size, suggest split).
7. **Plain language.** Say what happened and what to do next. No stack traces in the UI (details are one click away under "Show details"). Buttons are verbs ("Import images", not "Submit").
8. **Respect the user's data.** Nothing leaves the machine. Say so in the UI where it matters (AI-assist, weights download, remote workers).

## 2. Layout
- **Window shell:** left sidebar (Projects, Datasets, Annotate, Train, Monitor, Settings), top toolbar, main content, optional right inspector. Sidebar collapses under 900 px; inspector becomes a sheet under 700 px.
- **Annotator:** tool strip on the left edge of the canvas (Select, Box, Polygon, Keypoint, Pan, AI-assist), class list and annotation list in the inspector, filmstrip of images at the bottom.
- **Empty states** explain the next step with one primary button ("Import images to begin").
- **Sheets/popovers** for short tasks, full pages for long ones. No stacked modal dialogs.

## 3. Design tokens (CSS custom properties, defined once in `studio/web/css/tokens.css`)
| Token group | Rule |
|-------------|------|
| Colour | Semantic names (`--bg`, `--surface`, `--text`, `--text-secondary`, `--accent`, `--danger`, `--success`), light and dark values, one accent colour. Never raw hex in component CSS. |
| Type | `font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`. Scale 12/13/15/17/22/28 px. Weights 400/500/600. Tabular numerals for metrics. |
| Spacing | 4 px base: 4, 8, 12, 16, 24, 32. |
| Radius | 6 px controls, 10 px cards/sheets. |
| Motion | 120–200 ms ease-out; disabled under `prefers-reduced-motion`. |
| Elevation | Border + very light shadow; no heavy shadows. |
| Hit targets | At least 32 px high for pointer, 44 px for touch layouts. |
| Icons | Open icon set (Lucide or Phosphor, both permissive), 16/20 px, stroke weight consistent. |

## 4. Theming
Follow `prefers-color-scheme`, with a manual Light/Dark/System setting stored locally. Annotation colours per class are chosen from a colour-blind-safe palette and always paired with a text label.

## 5. Accessibility
- Every function reachable by keyboard; visible focus ring (2 px, accent); logical tab order.
- Contrast: 4.5:1 for text, 3:1 for UI components and focus rings, in both themes.
- Never use colour alone (add label, shape or pattern).
- Semantic HTML, ARIA labels on icon buttons, live regions for progress and errors.
- Respect `prefers-reduced-motion`; text resizes to 200 % without loss.
- Canvas actions have keyboard equivalents (arrow keys nudge, Tab cycles annotations).

## 6. Keyboard shortcuts (global, shown in a "?" cheat sheet)
| Action | Shortcut |
|--------|----------|
| Undo / Redo | Ctrl+Z / Ctrl+Shift+Z (Cmd on macOS) |
| Save | Ctrl+S (also autosaves) |
| Next / previous image | → / ← or D / A |
| Tools | V select · B box · P polygon · K keypoint · H pan |
| Delete annotation | Delete / Backspace |
| Duplicate annotation | Ctrl+D |
| Zoom | scroll or +/−, 0 = fit |
| Pan | Space-drag |
| Command palette | Ctrl+K |
| Shortcut sheet | ? |

## 7. Feedback and states
Every list/view defines: **empty**, **loading**, **error**, **populated**. Every async action defines: **idle**, **running** (progress), **done** (toast with Undo where possible), **failed** (what happened, what to do, Retry). Toasts auto-dismiss after 5 s unless they carry an error.

## 8. Hardware monitor and training screens
- One glanceable header: run state, epoch, ETA, current loss/metric.
- Charts share a time axis; hovering one shows the same instant on all. Units always shown (%, GB, °C, W).
- Warnings are specific: "VRAM 5.6 / 6.0 GB — lower the batch size to 8" with a one-click fix.

## 9. UX checklist (QA sign-off for every screen)
- [ ] Works end-to-end with keyboard only.
- [ ] Focus ring visible; tab order logical.
- [ ] Contrast checked in light and dark.
- [ ] Empty, loading, error and populated states exist and read well.
- [ ] Every destructive action is undoable or clearly confirmed.
- [ ] Every long task shows progress and can be cancelled.
- [ ] No jargon without an explanation; error messages say what to do.
- [ ] Layout holds at 700, 900 and 1440 px wide.
- [ ] Motion respects reduced-motion.
- [ ] Uses tokens only (no raw colours, sizes or fonts).
