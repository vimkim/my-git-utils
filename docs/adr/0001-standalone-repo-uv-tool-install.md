# Standalone repository installed as an editable uv tool

The log tools began as scripts deployed by chezmoi from the dotfiles
repository. They are expected to grow and to take third-party dependencies, so
they live in this standalone repository as one Python distribution and are
installed with `uv tool install --editable` (`just sync`). uv gives the commands
one isolated environment with the locked dependencies, and the editable install
makes code changes live without a deploy step. Chezmoi keeps only personal
state: the filter config (`~/.config/my-git-utils/log.toml`), shell aliases, and
a run-once bootstrap that clones this repository to `~/gh/my-git-utils` and runs
`just sync`; `daily-update` fast-forwards the checkout and re-syncs it.

## Considered options

- **Scripts deployed by chezmoi** (the previous state): no install step, but a
  deployed copy cannot be an editable install, dependencies have nowhere to
  live, and the project would share history with unrelated dotfiles.
- **`uv run --project` launchers**: one lock for development and runtime, but
  every call pays uv's start-up, and the environment lands next to whichever
  copy runs it, giving one `.venv` per copy.
- **PEP 723 `uv run --script` launchers**: no project venv, but Python and
  dependency declarations would be repeated in every launcher.
