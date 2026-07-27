#!/bin/bash
#
# software-audit.sh — inventory installed software on a macOS machine and
# report how each item was installed.
#
# Standalone: depends only on macOS built-ins. Homebrew, Nix, mas, and the
# various language package managers are all detected if present and skipped
# quietly if not. Safe to copy to any Mac and run; makes no changes.
#
# Usage:
#   ./software-audit.sh              # report on user-installed software
#   ./software-audit.sh --all        # also list Apple/system applications
#   ./software-audit.sh --origins    # show download URLs for manual installs
#   ./software-audit.sh --help
#
set -uo pipefail

SHOW_SYSTEM=0
SHOW_ORIGINS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --all)     SHOW_SYSTEM=1 ;;
    --origins) SHOW_ORIGINS=1 ;;
    -h|--help)
      # Print the header comment block, stopping at the first non-comment line.
      awk 'NR==1 {next} /^#/ {sub(/^# ?/,""); print; next} {exit}' "$0"
      exit 0 ;;
    *)
      echo "Unknown option: $1 (try --help)" >&2
      exit 1 ;;
  esac
  shift
done

# ---------------------------------------------------------------- helpers ---

BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
[ -t 1 ] || { BOLD=""; DIM=""; RESET=""; }

section() { printf '\n%s== %s ==%s\n' "$BOLD" "$1" "$RESET"; }
note()    { printf '%s%s%s\n' "$DIM" "$1" "$RESET"; }

# Read a key out of an app bundle's Info.plist, tolerating absence.
plist_get() {
  defaults read "$1/Contents/Info.plist" "$2" 2>/dev/null
}

TMPDIR_AUDIT=$(mktemp -d)
trap 'rm -rf "$TMPDIR_AUDIT"' EXIT
CASK_APPS="$TMPDIR_AUDIT/cask_apps"   # "AppName.app<TAB>cask-token"
: > "$CASK_APPS"

HAVE_BREW=0
if command -v brew >/dev/null 2>&1; then
  HAVE_BREW=1
elif [ -x /opt/homebrew/bin/brew ]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"; HAVE_BREW=1
elif [ -x /usr/local/bin/brew ]; then
  eval "$(/usr/local/bin/brew shellenv)"; HAVE_BREW=1
fi

# ------------------------------------------------------------------ header ---

printf '%smacOS Software Audit%s\n' "$BOLD" "$RESET"
printf 'Host    : %s\n' "$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
printf 'User    : %s\n' "$(whoami)"
printf 'macOS   : %s (%s)\n' "$(sw_vers -productVersion)" "$(uname -m)"
printf 'Date    : %s\n' "$(date '+%Y-%m-%d %H:%M')"

# ------------------------------------------------------------ homebrew ------

if [ "$HAVE_BREW" -eq 1 ]; then
  # Build the app -> cask map first; later sections use it to classify bundles.
  while IFS= read -r token; do
    [ -n "$token" ] || continue
    brew list --cask "$token" 2>/dev/null | grep '\.app$' | while IFS= read -r path; do
      printf '%s\t%s\n' "$(basename "$path")" "$token"
    done
  done < <(brew list --cask -1 2>/dev/null) >> "$CASK_APPS"

  section "Homebrew casks (GUI apps)"
  count=0
  while IFS= read -r token; do
    [ -n "$token" ] || continue
    ver=$(brew list --cask --versions "$token" 2>/dev/null | sed "s/^$token //")
    printf '  %-34s %s\n' "$token" "$ver"
    count=$((count + 1))
  done < <(brew list --cask -1 2>/dev/null)
  [ "$count" -eq 0 ] && note "  (none)"
  note "  $count cask(s)"

  section "Homebrew formulae (top-level)"
  count=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    printf '  %s\n' "$f"
    count=$((count + 1))
  done < <(brew leaves 2>/dev/null)
  [ "$count" -eq 0 ] && note "  (none)"
  total_formulae=$(brew list --formula 2>/dev/null | wc -l | tr -d ' ')
  note "  $count top-level, $total_formulae total including dependencies"

  section "Homebrew taps"
  taps=$(brew tap 2>/dev/null)
  if [ -n "$taps" ]; then printf '  %s\n' $taps; else note "  (none)"; fi
else
  section "Homebrew"
  note "  not installed"
fi

# --------------------------------------------------------- applications -----

# Classify every .app in the standard locations.
APP_DIRS=(/Applications "$HOME/Applications")
[ "$SHOW_SYSTEM" -eq 1 ] && APP_DIRS+=(/System/Applications)

MAS_LIST="$TMPDIR_AUDIT/mas"; : > "$MAS_LIST"
MANUAL_LIST="$TMPDIR_AUDIT/manual"; : > "$MANUAL_LIST"
SYSTEM_LIST="$TMPDIR_AUDIT/system"; : > "$SYSTEM_LIST"

for dir in "${APP_DIRS[@]}"; do
  [ -d "$dir" ] || continue
  for app in "$dir"/*.app; do
    [ -e "$app" ] || continue
    base=$(basename "$app")
    name="${base%.app}"
    ver=$(plist_get "$app" CFBundleShortVersionString)
    bid=$(plist_get "$app" CFBundleIdentifier)

    # Owned by a Homebrew cask? Already reported above.
    if grep -qF "$(printf '%s\t' "$base")" "$CASK_APPS" 2>/dev/null; then
      continue
    fi

    if [ -e "$app/Contents/_MASReceipt/receipt" ]; then
      printf '%s\t%s\t%s\n' "$name" "${ver:-?}" "${bid:-?}" >> "$MAS_LIST"
    elif [ "${app#/System/}" != "$app" ] || case "$bid" in com.apple.*) true ;; *) false ;; esac; then
      printf '%s\t%s\t%s\n' "$name" "${ver:-?}" "${bid:-?}" >> "$SYSTEM_LIST"
    else
      origin=""
      if [ "$SHOW_ORIGINS" -eq 1 ]; then
        # Spotlight records the download URL. Absent for anything copied in
        # by hand, built locally, or installed before Spotlight indexed it.
        raw=$(mdls -name kMDItemWhereFroms -raw "$app" 2>/dev/null)
        if [ -n "$raw" ] && [ "$raw" != "(null)" ]; then
          origin=$(printf '%s' "$raw" | tr -d '\n()"' | sed 's/^ *//; s/ *$//' | cut -c1-70)
        fi
      fi
      printf '%s\t%s\t%s\t%s\n' "$name" "${ver:-?}" "${bid:-?}" "$origin" >> "$MANUAL_LIST"
    fi
  done
done

section "Mac App Store"
if [ -s "$MAS_LIST" ]; then
  if command -v mas >/dev/null 2>&1; then
    note "  (IDs via mas; use these for nix-darwin homebrew.masApps)"
    mas list 2>/dev/null | sed 's/^/  /'
  else
    sort "$MAS_LIST" | while IFS=$'\t' read -r n v b; do
      printf '  %-34s %-12s %s\n' "$n" "$v" "$b"
    done
    note "  install mas (brew install mas) to also see App Store IDs"
  fi
else
  note "  (none)"
fi

section "Manually installed applications"
if [ -s "$MANUAL_LIST" ]; then
  note "  Not from Homebrew or the App Store — installed by hand (dmg/pkg/installer)."
  sort "$MANUAL_LIST" | while IFS=$'\t' read -r n v b o; do
    printf '  %-34s %-12s %s\n' "$n" "$v" "$b"
    [ -n "$o" ] && printf '  %-34s %s%s%s\n' "" "$DIM" "$o" "$RESET"
  done
  [ "$SHOW_ORIGINS" -eq 0 ] && note "  (pass --origins to show where each was downloaded from)"
else
  note "  (none)"
fi

if [ "$SHOW_SYSTEM" -eq 1 ]; then
  section "Apple / system applications"
  sort "$SYSTEM_LIST" | while IFS=$'\t' read -r n v b; do
    printf '  %-34s %-12s %s\n' "$n" "$v" "$b"
  done
fi

# ---------------------------------------------------------------- nix -------

section "Nix"
if command -v nix >/dev/null 2>&1; then
  printf '  nix     : %s\n' "$(nix --version 2>/dev/null)"
  if command -v darwin-rebuild >/dev/null 2>&1; then
    printf '  darwin  : nix-darwin active\n'
  else
    note "  nix-darwin not activated"
  fi
  if [ -e "$HOME/.nix-profile" ]; then
    note "  user profile packages:"
    nix profile list 2>/dev/null | sed 's/^/    /' | head -40
  fi
else
  note "  not installed"
fi

# ------------------------------------------------- language package mgrs ----

section "Language package managers"
found=0

if command -v npm >/dev/null 2>&1; then
  pkgs=$(npm ls -g --depth=0 2>/dev/null | tail -n +2 | sed 's/^[├└─│ ]*//' | grep -v '^$')
  if [ -n "$pkgs" ]; then
    printf '  %snpm (global)%s\n' "$BOLD" "$RESET"
    printf '%s\n' "$pkgs" | sed 's/^/    /'
    found=1
  fi
fi

if command -v pipx >/dev/null 2>&1; then
  pkgs=$(pipx list --short 2>/dev/null)
  if [ -n "$pkgs" ]; then
    printf '  %spipx%s\n' "$BOLD" "$RESET"
    printf '%s\n' "$pkgs" | sed 's/^/    /'
    found=1
  fi
fi

if command -v cargo >/dev/null 2>&1 && [ -d "$HOME/.cargo/bin" ]; then
  pkgs=$(cargo install --list 2>/dev/null | grep -v '^ ' | sed 's/:$//')
  if [ -n "$pkgs" ]; then
    printf '  %scargo%s\n' "$BOLD" "$RESET"
    printf '%s\n' "$pkgs" | sed 's/^/    /'
    found=1
  fi
fi

# Only report gems for a user-installed Ruby. macOS ships a system Ruby whose
# ~40 bundled gems are Apple's, not the user's, and drown out the signal.
if command -v gem >/dev/null 2>&1 && [ "$(command -v gem)" != "/usr/bin/gem" ]; then
  pkgs=$(gem list --no-versions 2>/dev/null | grep -v '^\*\*\*' | grep -v '^$')
  if [ -n "$pkgs" ]; then
    printf '  %sgem%s (%s)\n' "$BOLD" "$RESET" "$(command -v gem)"
    printf '%s\n' "$pkgs" | tr '\n' ' ' | fold -s -w 76 | sed 's/^/    /'
    echo
    found=1
  fi
fi

if command -v go >/dev/null 2>&1; then
  gobin="${GOBIN:-$HOME/go/bin}"
  if [ -d "$gobin" ]; then
    pkgs=$(ls -1 "$gobin" 2>/dev/null)
    if [ -n "$pkgs" ]; then
      printf '  %sgo install%s (%s)\n' "$BOLD" "$RESET" "$gobin"
      printf '%s\n' "$pkgs" | sed 's/^/    /'
      found=1
    fi
  fi
fi

[ "$found" -eq 0 ] && note "  (none found)"

# ------------------------------------------------------- loose binaries -----

section "Unmanaged CLI binaries"
note "  In PATH dirs that no package manager owns. Often dropped by app"
note "  installers (Docker Desktop, Ollama) rather than installed directly."
for d in /usr/local/bin "$HOME/.local/bin" /opt/local/bin; do
  [ -d "$d" ] || continue
  entries=$(ls -1 "$d" 2>/dev/null)
  [ -n "$entries" ] || continue
  printf '  %s%s%s\n' "$BOLD" "$d" "$RESET"
  printf '%s\n' "$entries" | tr '\n' ' ' | fold -s -w 76 | sed 's/^/    /'
  echo
done

# ---------------------------------------------------------------- summary ---

section "Summary"
if [ "$HAVE_BREW" -eq 1 ]; then
  printf '  %-28s %s\n' "Homebrew casks"    "$(brew list --cask -1 2>/dev/null | wc -l | tr -d ' ')"
  printf '  %-28s %s\n' "Homebrew formulae" "$(brew leaves 2>/dev/null | wc -l | tr -d ' ') top-level"
fi
printf '  %-28s %s\n' "Mac App Store apps" "$(wc -l < "$MAS_LIST" | tr -d ' ')"
printf '  %-28s %s\n' "Manually installed apps" "$(wc -l < "$MANUAL_LIST" | tr -d ' ')"
[ "$SHOW_SYSTEM" -eq 1 ] && \
  printf '  %-28s %s\n' "Apple/system apps" "$(wc -l < "$SYSTEM_LIST" | tr -d ' ')"
echo
