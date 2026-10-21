#!/usr/bin/env bash
# Run in an MSYS2 MINGW64 shell after installing the packages in QEMU.md.
set -euo pipefail
if [[ $# -ne 2 ]]; then
    echo "usage: bash build_msys2.sh QEMU_SOURCE BUILD_DIRECTORY" >&2
    exit 2
fi
source_dir=$(cd "$1" && pwd)
recipe_dir=$(cd "$(dirname "$0")" && pwd)
expected=4b667a1d3c08ab7a55835d15ddbd884fa754946d
[[ $(git -C "$source_dir" rev-parse HEAD) == "$expected" ]] || {
    echo "QEMU-EOS source does not match the pinned commit" >&2
    exit 2
}
[[ ${MSYSTEM:-} == MINGW64 ]] || { echo "Use MSYS2 MINGW64" >&2; exit 2; }
git -C "$source_dir" diff --no-ext-diff --binary HEAD | cmp - "$recipe_dir/windows-build.patch" || {
    echo "Source must have exactly the reviewed Windows patch applied" >&2
    exit 2
}
mkdir -p "$2"
cd "$2"
"$source_dir/configure" \
    --target-list=arm-softmmu --python=/usr/bin/python3 \
    --disable-werror --disable-docs --disable-git-update \
    --disable-plugins --disable-capstone --disable-slirp \
    --disable-gtk --disable-sdl --disable-curses --enable-vnc \
    --disable-guest-agent --disable-tools --disable-hax --disable-whpx \
    --extra-cflags=-std=gnu11
make -j4
