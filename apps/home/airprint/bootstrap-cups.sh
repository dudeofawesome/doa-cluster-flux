#!/bin/sh
set -o errexit
set -o nounset

queue="samsung-scx-4623-${NODE_NAME}"

until lpstat -r | grep --quiet --line-regexp --fixed-strings 'scheduler is running'; do
  sleep 1
done

uris="$(
  lpinfo -v \
  | awk '$1 == "direct" && $2 ~ /^usb:\/\/Samsung\/SCX-4623/ { print $2 }'
)"
uri_count="$(
  printf '%s\n' "$uris" \
  | sed '/^$/d' \
  | wc --lines \
  | tr --delete ' '
)"
[ "$uri_count" = 1 ] || {
  printf 'expected exactly one Samsung SCX-4623 USB URI, found %s\n' "$uri_count" >&2
  exit 1
}

models="$(
  lpinfo -m | awk '$1 == "drv:///splix-samsung.drv/scx4623f.ppd" { print $1 }'
)"
model_count="$(
  printf '%s\n' "$models" \
  | sed '/^$/d' \
  | wc --lines \
  | tr --delete ' '
)"
[ "$model_count" = 1 ] || {
  printf 'expected exactly one SpliX SCX-4623f driver, found %s\n' "$model_count" >&2
  exit 1
}

lpadmin -x "$queue" 2>/dev/null || true
lpadmin \
  -p "$queue" \
  -v "$uris" \
  -m "$models" \
  -D "Samsung SCX-4623" \
  -L "${NODE_NAME}" \
  -o printer-is-shared=true \
  -o media=Letter \
  -o sides=one-sided \
  -o print-color-mode=monochrome \
  -o resolution=600dpi \
;
cupsenable "$queue"
cupsaccept "$queue"
