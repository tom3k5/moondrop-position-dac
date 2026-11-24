#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT_DIR/pl.innovibe.DspControl.json"
BUILD_DIR="${BUILD_DIR:-$ROOT_DIR/.flatpak-build}"
REPO_DIR="${1:-$ROOT_DIR/dist/flatpak-repo}"

mkdir -p "$REPO_DIR"

flatpak-builder --force-clean --repo="$REPO_DIR" "$BUILD_DIR" "$MANIFEST"
flatpak build-update-repo --generate-static-deltas "$REPO_DIR"

install -Dm644 "$ROOT_DIR/flatpak/pl.innovibe.DspControl.flatpakrepo" \
  "$REPO_DIR/pl.innovibe.DspControl.flatpakrepo"
install -Dm644 "$ROOT_DIR/flatpak/pl.innovibe.DspControl.flatpakref" \
  "$REPO_DIR/pl.innovibe.DspControl.flatpakref"
install -Dm644 "$ROOT_DIR/flatpak/pl.innovibe.DspControl.svg" \
  "$REPO_DIR/pl.innovibe.DspControl.svg"

echo "Static OSTree Flatpak repository ready in: $REPO_DIR"
echo "Deploy contents of $REPO_DIR to https://innovibe.pl/flatpak/"
