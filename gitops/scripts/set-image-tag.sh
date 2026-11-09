#!/usr/bin/env bash
# values 파일의 image.tag 한 줄만 바꾼다(주석·순서는 그대로). CI 태그 커밋과 prod 승격 PR에서 쓴다.
# 사용: scripts/set-image-tag.sh <태그> <values 파일> [<values 파일> ...]
#   예) scripts/set-image-tag.sh 3f2a...c1 apps/_shared/spring-dev.yaml
# yq 없이 동작하도록 awk로 "image:" 블록 안의 첫 "tag:"만 바꾼다. 블록에 tag가 없으면 실패한다.
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "사용: $0 <태그> <values 파일>..." >&2
  exit 2
fi
tag="$1"; shift
if [ "$tag" = "latest" ] || ! printf '%s' "$tag" | grep -Eq '^[A-Za-z0-9._-]{1,128}$'; then
  echo "잘못된 태그: $tag (latest 금지, 커밋 SHA 사용)" >&2
  exit 2
fi

for file in "$@"; do
  tmp="$(mktemp)"
  awk -v tag="$tag" '
    /^image:[[:space:]]*$/ { in_image = 1; print; next }
    in_image && /^[^[:space:]#]/ { in_image = 0 }
    in_image && !done && /^[[:space:]]+tag:/ {
      match($0, /^[[:space:]]+/)
      print substr($0, 1, RLENGTH) "tag: \"" tag "\""
      done = 1
      next
    }
    { print }
    END { if (!done) exit 3 }
  ' "$file" > "$tmp" || { rc=$?; rm -f "$tmp"; echo "image.tag를 찾지 못함: $file" >&2; exit "$rc"; }
  mv "$tmp" "$file"
  echo "$file → $tag"
done
