#!/usr/bin/env bash
set -euo pipefail
snapflow_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
snapflow_session="snapflow-$(date +%m%d)"
snapflow_work="$snapflow_root/../tmp/snapflow-runtime"
mkdir -p "$snapflow_work"
export TMPDIR="$snapflow_work"
snapflow_socket="$snapflow_work/tmux.sock"
snapflow_log="$snapflow_work/server-$(date +%Y%m%d).log"
if ! command -v tmux >/dev/null; then
  echo 'tmux is required for this Linux launcher. Install tmux, then retry.'
  exit 1
fi
if ! tmux -S "$snapflow_socket" has-session -t "$snapflow_session" 2>/dev/null; then
  printf -v snapflow_command 'cd %q && python3 -B -u server.py 2>&1 | tee -a %q' "$snapflow_root" "$snapflow_log"
  tmux -S "$snapflow_socket" new-session -d -s "$snapflow_session" "$snapflow_command"
fi
echo 'SnapFlow default URL: http://127.0.0.1:8765 (or PORT configured in .env)'
printf 'Log: %s\n' "$snapflow_log"
printf 'Inspect: tmux -S %q list-sessions\n' "$snapflow_socket"
printf 'Stop after use: tmux -S %q send-keys -t %q C-c\n' "$snapflow_socket" "$snapflow_session"
