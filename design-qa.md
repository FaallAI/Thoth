# Dashboard .pen fidelity verification

Date: 2026-10-01. Source: `design/thoth-dashboard.pen` version 2.19.

Result: frontend geometry and supported behavior verified. This is not a claim of
full pixel equality of production data, media content, or unavailable operations.
No actionable P0/P1/P2 frontend defect remains in the checked scope; the contract
limitations below remain explicit. No backend, API client, generated contract,
dependency manifest, operator design asset, live provider, or publication change.

## Method and geometry

Measured the source JSON, visually inspected the six exports and interaction atlas,
and compared equal-scale rendered captures at the source's 1440 x 900 viewport.
Narrow checks use 375 x 812. All network/API responses are synthetic/intercepted;
no real secret, fixture, TikTok/provider request, or operational observation is used.

Inter is shipped locally under its OFL license. Automatic optical sizing caused
the original width drift and is disabled. Browser font rasterization and fractional
line boxes still differ from the design renderer by approximately 1–3px (P3).

| Region | Verified desktop dimensions |
|---|---|
| Shared header / sidebar | 1440 x 66 / 222 x 834 |
| Main content start | x264, heading y100, first panel y207.594 |
| Workflows | metrics92; launch771/monitor345 x332; Recent runs219 |
| Discovery | stages75; panels330/786 x459; footer60 |
| Content Set | brief74; panels756/360 x515 |
| Profiles | columns285/559/254 x613 |
| Legacy Console | metrics68; columns315/801 x567 |
| Studio Simple | header70; inspector356 x602; scene tray1440 x228 |
| Studio preview frame | 274 x518 at x405,y101.5 |

Offline comparison: `http://127.0.0.1:5179/index.html`.
Saved report: `C:/Users/mfr/.codex/visualizations/2026/09/30/01a0f3ec-6576-72f3-ad55-f094ebf31ac8/pen-fidelity/comparison/index.html`.
Six combined comparison images are `comparison-0.png` through `comparison-5.png`
in that folder. Its selector exposes captured interaction states; reference
interaction/control atlases remain the supplied operator exports.

## All source states

Capture root A: `C:/Users/mfr/.codex/visualizations/2026/09/30/01a0f3ec-6576-72f3-ad55-f094ebf31ac8/pen-fidelity/`.
Capture root B: `C:/Users/mfr/.codex/visualizations/2026/09/30/01a0f3ec-6576-72f3-ad55-f094ebf31ac8/`.
Capture root C: `.superpowers/sdd/2026-10-01-dashboard-pen-fidelity/profiles-legacy-captures/`.

| Source frame | Actual capture |
|---|---|
| Workflows | A/01-workflows-running-1440.png |
| Discovery | B/pen-discovery-1440.png |
| Content Set | B/pen-content-set-1440.png |
| Profiles | C/profiles-1440.png |
| Legacy Console | C/legacy-1440.png |
| Creator Studio | B/pen-studio-simple-1440.png |
| Top bar · Search open | A/header-search.png |
| Top bar · Project picker open | A/header-project-picker.png |
| Top bar · Profile menu open | A/header-workspace-menu.png |
| Workflows · New workflow open | A/workflow-draft-default.png |
| New workflow · Guided selected | A/workflow-draft-guided.png |
| New workflow · Blank selected | A/workflow-draft-blank.png |
| New workflow · Choose first step | A/workflow-draft-first-step.png |
| Creator Studio · Advanced | B/pen-studio-advanced-1440.png |
| Caption style open | B/pen-studio-caption-style-1440.png |
| Preview playing | B/pen-studio-preview-playing-1440.png |
| Adjust media open | B/pen-studio-adjust-1440.png |
| Advanced media selected | B/pen-studio-advanced-media-selected-1440.png |
| Media details open | B/pen-studio-media-details-1440.png |
| Replace media open | B/pen-studio-replace-1440.png |
| Prompt Lab | B/pen-studio-prompt-1440.png |
| Prompt Lab · Visual plan | B/pen-studio-prompt-visual-plan-1440.png |
| Prompt Lab · Caption and copy | B/pen-studio-prompt-caption-and-copy-1440.png |
| Review | B/pen-studio-review-1440.png |
| Render | B/pen-studio-render-1440.png |

## Expected differences from sample data and unsupported operations

- The workflow API has no aggregate statistics, global history, workflow project
  association, source title, run-time estimate, or per-stage approval setting.
  Metrics and associations use empty values. History/search use actual workflows
  observed this session. Live source URL, progress, stages, and outputs stay real.
- Workflow creation selects Guided or Blank and the first step, but the existing
  server has no reusable arbitrary workflow draft/editor API. Creation is explicitly
  session-local; blank/custom execution is blocked. Nothing starts or publishes.
- Discovery exposes actual Scout search/discovery operations. Saved/region/YouTube
  collection modes explain availability. Source totals, readiness claims, unknown
  scene counts, historical ages, and candidate descriptions are not fabricated.
- Profile creative principle strings and usage counts have no contract. The rows
  summarize actual settings; the existing complete settings editor remains accessible.
  Unsupported account preferences/sign-out are disabled with explanations.
- Legacy aggregate needs-review/failed-today and per-stage completion are not known.
  Retry and stage approval have no job API and remain disabled. Job state, progress,
  cancel, artifact cleanup confirmation, outputs/review, and log auto-follow stay real.
- Studio uses the actual document's source title, project, scene count, assets, saved
  revision, timeline, and Remotion composition. The reference Kyoto video is never
  substituted for user media. The isolated fixture declares a synthetic media asset
  without a playable capability, so its unavailable preview differs from the sample.
  Native Player time/mute controls retain real behavior and their native time format.
- Scene media details/replace/adjust surfaces are present. Replacement and fit/crop
  writes from those panels are unavailable and explained; supported Advanced clip
  editing remains available. Document rename is unavailable. Caption styling offers
  actual supported style slots rather than asserting the sample cinematic preset.
- Prompt templates, providers, resolved text, review decisions/comments, render jobs,
  and thumbnails reflect available data. Missing bindings/providers/results are
  honest empty states. The synthetic fixture exercises all three Prompt stages.

## Evidence and limits

37 captured desktop/phone states: root11, Discovery/Content5, Profiles/Legacy4,
Studio17. Zero page errors, foreign/unmatched requests, or horizontal page overflow.
Studio has one mounted Player through all jobs. The 234-line Legacy SSE fixture
reaches bottomGap=0 at both widths; cancel/cleanup controls remain within their panel.
New-run profile dropdown is usable above the shared dialog. Keyboard navigation,
candidate list scrolling, unavailable-source explanations, evidence removal,
save-before-render, project pinning, and local-draft API-write prevention are checked.

Final CUDA/dashboard build/test/lint evidence is recorded in the active checkpoint
and CHANGELOG. Coordinator review covered the integration; an independent final
review attempt failed because the reviewer reported an account usage limit.
