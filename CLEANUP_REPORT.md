# CLEANUP_REPORT.md

Repository: ReSerendipity/seedvr2
Scan date: 2026-08-06
Large-file threshold: 5 MB

Summary of findings

1) Current HEAD items of concern
- log.txt — 108,465 bytes
  Recommendation: remove from index (non-destructive) and ignore going forward. See remove_tracked_sample_seedvr2.sh for commands.

2) Noted directories
- logs/ (contains .gitkeep) — intended runtime logs; should stay ignored.
- pretrained_models/, models/ — currently empty or placeholders; these directories are expected to hold model weights and should be ignored (or moved to LFS/external storage).

Recommendations (safe/non-destructive)

A) Non-destructive removal (recommended first step)
- Run the provided remove_tracked_sample_seedvr2.sh locally to remove log.txt from the index, then push a branch and open a PR.

B) Historical purge (destructive — DO NOT run without coordination)
- If you need to remove files from the repository history, use git filter-repo or BFG. This rewrites history and requires force-push and coordination with all contributors.

C) Long-term strategy
- Use Git LFS or external object storage (S3 / HF Hub) for model weights.
- Keep runtime artifacts (logs, outputs, uploads) out of Git; ensure .gitignore covers them.

Files added in this branch
- CLEANUP_REPORT.md (this file)
- history_scan.sh (history scanning helper)
- remove_tracked_sample_seedvr2.sh (non-destructive removal example)
- GITIGNORE_UPDATE.md (recommended .gitignore snippets and instructions)

