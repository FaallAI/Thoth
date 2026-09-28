# Gemini prompt — Creator Studio F3 design prototype

Copy the fenced prompt below into Gemini from the repository root.

```text
Repository: C:\Users\mfr\Documents\MyTools\CLIPPER
Mode: DESIGN_ONLY — produce and verify a reviewable UI/UX design prototype in design/. Do not implement product code.

Read in this order:
1. AGENTS.md and C:\Users\mfr\.codex\RTK.md.
2. .superpowers/sdd/2026-09-25-creator-studio-f3-first-mode-migration/progress.md and .superpowers/sdd/2026-09-24-creator-studio-f3-ux-first-migration/progress.md.
3. design/PRD.md and design/DESIGN.md.
4. docs/superpowers/specs/2026-09-24-creator-studio-f3-ux-first-migration-design.md, then docs/superpowers/specs/2026-09-25-creator-studio-f3-full-ui-ux-design.md.
5. docs/superpowers/specs/2026-09-24-creator-studio-responsive-review-design.md and docs/superpowers/specs/2026-09-11-ui-first-creator-studio-design.md.
6. docs/superpowers/plans/2026-09-24-creator-studio-f3-workspace-ux.md and docs/superpowers/plans/2026-09-25-creator-studio-f3-first-mode-migration.md.
7. design/README.md, design/index.html, design/dummy_data.json, and docs/superpowers/specs/2026-09-24-creator-studio-f3-selected-direction.png.

Use https://github.com/google-labs-code/design.md as the format reference for design/DESIGN.md: its YAML front matter supplies normative tokens and its Markdown body explains their use. Preserve the token values and product boundaries already recorded there. If you find a genuine conflict between PRD, DESIGN.md, source specs, and the current prototype, report it instead of silently choosing a new product behavior.

Process: invoke the applicable Superpowers skill first as AGENTS.md requires. For prototype code, apply Ponytail at full intensity and the Karpathy Guidelines: trace the existing flow, make the smallest change that satisfies this brief, and verify it with one meaningful runnable check. Keep repository artifacts in English.

Preflight: record actual HEAD/branch and git status, compare the active checkpoints to current files, and inspect existing design/ changes before editing. This prompt was prepared when HEAD was 259782e on master, ahead of origin/master by 24, with only the three new design documents untracked. Treat that as context, not a reset target; another task may advance HEAD. Preserve all operator-owned and unrelated changes. Do not start a new product implementation or assume an earlier plan's completion status is current without checking drift.

Deliverables, all inside design/:
- Refine the existing self-contained interactive prototype rather than replacing it blindly. Demonstrate the full PRD journey: Content Set entry choice, draft Resume/Create, complete import inventory and resolution, Edit Simple and Advanced, Prompt, Review, and Render.
- Show representative saved/dirty/saving/failed/conflict/offline and import/render blocked states. Use realistic non-live fixture data. Every visible product action must have meaningful prototype behavior; put simulator/state-switch controls outside the product canvas and label them as prototype tools.
- Match design/DESIGN.md and the selected dark direction while following the behavior and responsive capability matrices. Show 1440, 1120/1024, 820, and 375 px layouts, plus 200% zoom. Keep one visual preview, clear revision cues, textual statuses, 44 px compact targets, keyboard/focus behavior, and reduced-motion support.
- Update design/README.md with run instructions, a screen/state-to-PRD mapping for UI-01 through UI-12, and an honest list of simulated behavior and remaining gaps. Add local assets under design/assets only if essential; do not add a framework, dependency, or remote runtime requirement for this standalone prototype.

Verification: run the existing design/serve.py flow or open design/index.html, inspect each required viewport and key state in a browser, verify keyboard traversal and 200% zoom, check for horizontal overflow and inaccessible controls, and run any relevant lightweight validation available for the changed design files. Report observed results and limits; do not claim an unrun test passed. If you edit design/DESIGN.md, lint it with the Windows-compatible command `npx -p @google/design.md designmd lint design/DESIGN.md` when available, and report any unavailable registry/tool limitation.

Preservation and hard stops: do not edit dashboard/, python/, scout/, Rust crates, production schemas, SDD checkpoints, CHANGELOG.md, approval records, or evidence. Do not access real secrets or fixtures, call live TikTok/providers, upload to S3, start a real render, publish, push, deploy, restart services, promote golden output, activate soak, or perform cutover. Keep prototype data local and synthetic. Do not silently resolve a source-spec conflict by inventing a product feature. Stop and ask the operator only if a material product decision cannot be represented safely in the prototype.

Final report in Indonesian: (1) files changed, (2) which PRD screens/states are demonstrated, (3) verification actually run with outcomes, (4) simulated behavior and open design decisions, (5) current git status and the next operator review checkpoint. Repository artifacts, code, comments, and documentation must remain English.
```
