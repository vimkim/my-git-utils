# Agent notes

- Read `README.md` for behavior and `GLOSSARY.md` for terms; use the glossary's
  words (PR head, PR base, upstream, label, mark, hidden ref) in code and docs.
- Layout: one distribution, one subpackage per tool family
  (`src/my_git_utils/log/`). Entry points are in `pyproject.toml`.
- Check every change with `just test` and `just lint`.
- `just sync` reinstalls the user's global commands from this checkout; run it
  only from the main checkout, never from a task worktree.
- Record hard-to-reverse decisions with real trade-offs in `docs/adr/`.
