#!/usr/bin/env bash
# Puts the rendered module into a BCR checkout and lets BCR's own tools examine
# it. The publish step and the presubmit rehearsal use this script.
#
#   tools/common/stage_into_bcr.sh <BCR checkout> [render.py options]
#
# It does no git operation and it pushes nothing. After it, the checkout holds
# the new version as changes that are not committed.
set -euo pipefail

bcr="$(cd "${1:?usage: stage_into_bcr.sh <BCR checkout> [render.py options]}" && pwd)"
shift
root="$(cd "$(dirname "$0")/../.." && pwd)"
[[ -f "$bcr/tools/bcr_validation.py" ]] || { echo "stage: $bcr is not a BCR checkout" >&2; exit 2; }

out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
"$root/tools/common/render.py" --out "$out" "$@" >/dev/null

name="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["module"])' "$root/upstream.json")"
version="$(cd "$out/registry/modules/$name" && ls -d */ | tr -d /)"
target="$bcr/modules/$name/$version"
echo "stage: $name@$version -> $target"

if [[ -e "$target" ]]; then
  echo "stage: BCR already has $name@$version. A BCR version is permanent; use bcr_revision in upstream.json for a fix." >&2
  exit 3
fi
[[ -d "$bcr/modules/$name" ]] || { echo "stage: BCR has no module $name; the first version of a module is manual work" >&2; exit 3; }

cp -R "$out/registry/modules/$name/$version" "$target"
# BCR owns metadata.json: a co-maintainer can be in it that this repository does
# not know. BCR's update_integrity adds the new version to the list.
if ! cmp -s "$out/registry/modules/$name/README.md" "$bcr/modules/$name/README.md"; then
  cp "$out/registry/modules/$name/README.md" "$bcr/modules/$name/README.md"
  echo "stage: README.md changed"
fi

# BCR's tool must calculate the same source.json. If it does not, the renderer
# and BCR disagree, and that is an error of this repository.
cp "$target/source.json" "$out/source.json.ours"
(cd "$bcr" && bazel run //tools:update_integrity -- "$name" --version="$version" >/dev/null 2>&1)
if ! cmp -s "$out/source.json.ours" "$target/source.json"; then
  echo "stage: BCR's update_integrity changed source.json:" >&2
  diff "$out/source.json.ours" "$target/source.json" >&2 || true
  exit 4
fi
echo "stage: BCR's update_integrity gives the same source.json"

report="$out/validation.txt"
(cd "$bcr" && bazel run //tools:bcr_validation -- --check="$name@$version" 2>&1) | sed 's/\x1b\[[0-9;]*m//g' | grep -E "BcrValidationResult" > "$report" || true
cat "$report"
if grep -q "BcrValidationResult.FAILED" "$report"; then
  echo "stage: bcr_validation found a failure" >&2
  exit 5
fi
if grep -q "NEED_BCR_MAINTAINER_REVIEW" "$report"; then
  echo "stage: a BCR maintainer must review this version; say so in the pull request"
fi
echo "stage: $name@$version is in $bcr and passed bcr_validation"
