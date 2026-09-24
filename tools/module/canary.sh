#!/usr/bin/env bash
# The canary of sdl3: diff_config.sh must fail for a generated header whose
# #define set differs from the oracle, and must pass when only the lines that
# do not count differ.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
status=0
expect() {  # name, wanted exit code (0 or "fail"), command...
  local name="$1" want="$2"; shift 2
  "$@" >/dev/null 2>&1; local got=$?
  if { [[ "$want" == 0 && $got == 0 ]] || [[ "$want" == fail && $got != 0 ]]; }; then echo "ok   $name"; else echo "FAIL $name  <- exit $got"; status=1; fi
}
oracle="$tmp/oracle.h"
printf '#define HAVE_STDIO_H 1\n#define SDL_VIDEO_DRIVER_X11 1\n#define SDL_XKBCOMMON_VERSION_MINOR 7\n/* #undef SDL_VIDEO_OPENGL_GLX */\n' > "$oracle"
printf '#undef SDL_VIDEO_OPENGL_GLX\n#define SDL_XKBCOMMON_VERSION_MINOR 5\n#define SDL_VIDEO_DRIVER_X11 1\n#define  HAVE_STDIO_H   1\n' > "$tmp/same.h"
printf '#define HAVE_STDIO_H 1\n#define SDL_VIDEO_DRIVER_X11 1\n#define HAVE_NEW_THING 1\n' > "$tmp/extra.h"
printf '#define SDL_VIDEO_DRIVER_X11 1\n' > "$tmp/absent.h"
printf '#define HAVE_STDIO_H 1\n#define SDL_VIDEO_DRIVER_X11 0\n' > "$tmp/value.h"
expect "oracle: the same defines pass; the order, the spaces, an #undef and the xkbcommon version do not count" 0 "$here/diff_config.sh" "$tmp/same.h" "$oracle"
expect "oracle: a define that the oracle does not have fails" fail "$here/diff_config.sh" "$tmp/extra.h" "$oracle"
expect "oracle: a define that the oracle has and the header does not fails" fail "$here/diff_config.sh" "$tmp/absent.h" "$oracle"
expect "oracle: a different value fails" fail "$here/diff_config.sh" "$tmp/value.h" "$oracle"
exit $status
