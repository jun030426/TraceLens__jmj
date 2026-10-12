# Project instructions

- Work in the current device's verified checkout. On the Windows RTX 4060 laptop this is `C:\Users\USER\dev\Lerny`; the previous PC used `D:\캡스톤디자인_Lerny`.
- The primary repository is now `https://github.com/jun030426/TraceLens__jmj`, default branch `master`. The product name remains Lerny. See `docs/15_저장소_이전과_개발_인수인계.md` for the migration and current development context. Verify the actual remote/branch before continuing work; the checkout folder need not match the repository name.
- Do not push, create or modify GitHub repositories, branches, pull requests, or other remote state without the user's explicit authorization for that action. A development request does not authorize remote writes.
- Use the functional specification and `docs/00_개발_착수_기준.md` as the product baseline. Per the user's 2026-10-09 revision, use `jun030426/TraceLens-test` as a reference for screen flow and button interactions, not visual design. Keep real backend behavior and agreed product policies; do not copy mock data or mock authentication.
- Use free local tools and locally executed models. No external LLM APIs or automatic cloud fallback.
- Keep models, package caches, virtual environments and runtime data outside the source tree. Use `LERNY_RUNTIME_ROOT`, defaulting to `%USERPROFILE%\LernyData`. Never commit secrets or student/professor data.
- Do not execute student code on the host. Keep execution disabled until Linux isolation is configured and verified.
- Do not restart the user's PC automatically. Record environmental blockers accurately; do not mark P0 complete before its checks pass.
