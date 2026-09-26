#!/usr/bin/env bash
# Compares the #define set of the Linux build config that the module generates
# with a CMake oracle from tools/module/gen_linux_build_config.sh.
#
#   tools/module/diff_config.sh <generated SDL_build_config.h> <oracle header>
#
# Only `#define` lines count: the oracle keeps CMake's `/* #undef X */`
# comments and autoconf writes its own, and neither reaches the compiler.
#
# Three entries record the version of a header package. The oracle sees the
# package of the image, the module the BCR module that MODULE.bazel pins, so
# they are excluded: the xkbcommon and libdecor version macros, and the XInput2
# gesture check, which needs libXi 1.8 (Ubuntu 20.04 has 1.7.10; BCR has 1.8.2):
# https://github.com/libsdl-org/SDL/blob/release-3.4.16/cmake/sdlchecks.cmake#L465-L467
set -euo pipefail

generated="$1"
oracle="$2"

defines() {
    grep -E '^#define ' "$1" \
        | grep -vE '^#define (SDL_(XKBCOMMON|LIBDECOR)_VERSION_|SDL_VIDEO_DRIVER_X11_XINPUT2_SUPPORTS_GESTURE )' \
        | sed -E 's/[[:space:]]+/ /g; s/ $//' \
        | sort
}

if diff <(defines "$oracle") <(defines "$generated"); then
    echo "diff_config: the define sets are identical ($(defines "$oracle" | wc -l) defines)"
else
    echo "::error::the generated config differs from the oracle ($oracle): < oracle only, > generated only" >&2
    exit 1
fi
