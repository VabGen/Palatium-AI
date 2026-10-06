#!/usr/bin/env bash
# =============================================================================
# PID-1 supervisor for the upstream ClamAV entrypoint (/init).
# =============================================================================
# Why this file exists — read from clamav/clamav:1.5.4-debian `/init` directly:
#
#   if [ "${CLAMAV_NO_CLAMD:-false}" != "true" ]; then
#       ...
#       clamd --foreground &
#       ...
#   fi
#   exec tail -f "/dev/null"
#
#   The daemon is started *detached* and PID 1 becomes `tail`. So when clamd is
#   reaped — it holds the largest RSS in the stack, which makes it the usual OOM
#   victim — the container keeps reporting `Up` (and a plain TCP healthcheck can
#   even survive on a socket nothing answers on), while every upload blocks until
#   the application's scan timeout. That is the "attachment via the paperclip
#   hangs for 30s" symptom, and no restart policy can fire because nothing died.
#
# What this does: run /init in the background and fail the container as soon as
# the daemon stops answering on its TCP socket (or /init itself exits). With
# `restart: unless-stopped` Docker then rebuilds the container, so clamd *and* its
# in-memory signature database come back instead of the failure staying silent.
#
# The startup phase is deliberately not policed: a cold container spends minutes
# in freshclam before clamd exists, and /init already owns that timeout
# (CLAMD_STARTUP_TIMEOUT, default 1800s). The watchdog only reacts once the
# socket has answered at least once, and otherwise propagates /init's own exit.
#
# Deliberately dependency-free: bash builtins plus `cat` from the image. There is
# no python3, no pgrep and no curl in this image (verified 2026-09).
# =============================================================================
set -euo pipefail

# clamd's own default in this image (`/etc/clamav/clamd.conf`: `TCPSocket 3310`);
# the compose file publishes exactly this port.
readonly CLAMD_TCP_PORT="${CLAMD_TCP_PORT:-3310}"
readonly POLL_INTERVAL_SECONDS="${CLAMD_WATCHDOG_INTERVAL_SECONDS:-10}"

# PID 1's child (/init, and after its `exec`, `tail`) is alive and not a zombie.
# A zombie still satisfies `kill -0`, so the state letter from /proc/<pid>/stat is
# what tells us the child is really gone; `read` is a bash builtin, so this stays
# available even in a stripped image.
child_alive() {
    local pid comm state rest
    read -r pid comm state rest < "/proc/${init_pid}/stat" 2>/dev/null || return 1
    [ "${state}" != "Z" ]
}

# Is the daemon accepting connections? This is the same contract the application
# uses (ATTACHMENTS_CLAMAV_* → clamd INSTREAM over TCP), so it also catches a clamd
# that is alive but wedged, not just a reaped one.
clamd_answering() {
    (exec 3<>"/dev/tcp/127.0.0.1/${CLAMD_TCP_PORT}") 2>/dev/null
}

/init &
init_pid=$!

# `docker stop` must stay a clean shutdown: forward the signal to /init, which is
# what the daemon's process tree actually listens to.
trap 'kill -TERM "${init_pid}" 2>/dev/null || true' TERM INT

clamd_seen=0
while child_alive; do
    if clamd_answering; then
        clamd_seen=1
    elif [ "${clamd_seen}" -eq 1 ]; then
        echo "clamd-watchdog: clamd stopped answering on port ${CLAMD_TCP_PORT}; exiting so the restart policy can recover it" >&2
        kill -TERM "${init_pid}" 2>/dev/null || true
        exit 1
    fi
    sleep "${POLL_INTERVAL_SECONDS}"
done

# Propagate /init's own outcome: 0 only if the entrypoint itself decided to stop.
if wait "${init_pid}"; then
    echo "clamd-watchdog: /init exited cleanly" >&2
    exit 0
fi
echo "clamd-watchdog: /init exited with an error" >&2
exit 1
