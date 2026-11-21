#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/serv-editor.XXXXXX")"
trap 'rm -rf "$build_dir"' EXIT

cp "$repo_root/tools/editor/package.json" "$repo_root/tools/editor/package-lock.json" "$build_dir/"
cp "$repo_root/tools/editor/editor.js" "$build_dir/"
(cd "$build_dir" && npm ci --ignore-scripts --no-audit --no-fund)
"$build_dir/node_modules/.bin/esbuild" "$build_dir/editor.js" \
  --bundle --minify --format=iife --outfile="$repo_root/data/js/editor.js"
