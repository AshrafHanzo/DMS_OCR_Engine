#!/usr/bin/env bash
#
# Build the installer bundle to hand to a customer.
#
# WHY A BUNDLE AND NOT "git clone"
#
# This repository is private, so a customer cannot clone it -- and it must STAY private,
# because it contains real client material:
#
#   ocr/test_doc2.pdf          a Karnataka government letter
#   ocr/test_output_*.docx     four documents derived from it
#   ocr/aligned_out*/          rendered pages from the same scan
#
# Worse, ocr/main.py mounts StaticFiles over its own directory, so anything sitting in
# ocr/ is downloadable from the engine's port. Shipping the repository as-is would put
# one client's document on another client's server AND serve it over HTTP.
#
# So this builds an ALLOWLIST bundle: only the files the engine needs, then a scan that
# refuses to produce a tarball if anything that looks like infrastructure or a secret
# survived. An allowlist because a denylist is one forgotten file away from a leak, and
# the forgotten file is discovered by the customer.
#
# USAGE
#
#   ./deploy/make-bundle.sh                 -> dms-ocr-engine-<sha>.tar.gz
#   ./deploy/make-bundle.sh --out /tmp      -> writes there instead
#
# Then send the customer the tarball and deploy/CUSTOMER-SETUP.md.

set -euo pipefail

OUT_DIR="."
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT_DIR="$2"; shift 2 ;;
    -h|--help) awk '/^# USAGE/{f=1} /^set -euo/{exit} f{sub(/^# ?/,""); print}' "$0"
               exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ok()   { printf '   \033[32mok\033[0m   %s\n' "$*"; }
warn() { printf '   \033[33mwarn\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mrefused:\033[0m %s\n' "$*" >&2; exit 1; }

# Everything the engine needs at runtime, and nothing else. Anything not listed here
# does not ship -- including our own deploy notes, which carry server addresses.
INCLUDE=(
  requirements.txt
  verify_deploy.py
  ocr/main.py
  ocr/aligned_pipeline.py
  ocr/docx_generator.py
  # The built-in UI. main.py mounts this directory, so these three are what the mount
  # is FOR; without them the engine starts but its own page 404s.
  ocr/index.html
  ocr/app.js
  ocr/styles.css
  deploy/install.sh
  deploy/CUSTOMER-SETUP.md
)

# Deliberately NOT included, each for a reason worth stating:
#   compare_engines.py      hard-codes the Jetson's address
#   deploy/README.md        our deploy notes, contains the DMS server address
#   deploy/dms-ocr.service  install.sh generates its own with the customer's paths;
#                           shipping ours invites someone to copy the wrong paths
#   DEPLOY*.md/.txt         internal, contains addresses and history
#   ocr/test_doc2.pdf       a real client document
#   ocr/test_*, aligned_out*, annex_out, rev_*, *.xlsx
#   ocr/OCRmyPDF, ocr/venv, ocr/tessdata, gs_installer.exe

STAMP="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
NAME="dms-ocr-engine-${STAMP}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "staging ${#INCLUDE[@]} file(s)"
for f in "${INCLUDE[@]}"; do
  [ -f "$f" ] || die "missing from the repo: $f"
  mkdir -p "$STAGE/$NAME/$(dirname "$f")"
  cp "$f" "$STAGE/$NAME/$f"
done
ok "staged"

# ── the scan that decides whether this ships ─────────────────────────────────
# Runs on the STAGED copy, so it sees exactly what the customer would receive.
echo
echo "scanning the staged files"
FOUND=0

# IPv4, excluding loopback and documentation ranges. An address here is either our
# infrastructure or another client's.
# A version number looks exactly like an address: PyMuPDF==1.27.2.3 tripped this on the
# first run. So every octet must be legal, and a line carrying a version pin is not
# treated as an address. Narrowing the pattern rather than the file list, because
# excluding requirements.txt from the scan would also stop it catching a real one.
HITS=$(grep -rnoE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' "$STAGE" 2>/dev/null |
       grep -vE '127\.0\.0\.1|0\.0\.0\.0|255\.' |
       awk -F: '{ n=split($NF, o, "."); ok=1
                  for (i=1; i<=4; i++) if (o[i]+0 > 255) ok=0
                  if (ok) print }' |
       while IFS= read -r hit; do
         f="${hit%%:*}"; r="${hit#*:}"; ln="${r%%:*}"
         src=$(sed -n "${ln}p" "$f" 2>/dev/null)
         case "$src" in
           *==*|*'>='*|*'<='*|*'~='*) ;;   # a dependency pin, not a host
           *) printf '%s\n' "$hit" ;;
         esac
       done || true)
if [ -n "$HITS" ]; then
  echo "$HITS" | sed "s|$STAGE/$NAME/||" | sed 's/^/     /'
  FOUND=1
fi

# Credentials. Matches the assignment form, so prose about passwords does not trip it.
CRED=$(grep -rniE '(password|passwd|secret|api[_-]?key|token)[[:space:]]*[:=][[:space:]]*['"'"'"][^'"'"'"]{3,}' \
       "$STAGE" 2>/dev/null || true)
if [ -n "$CRED" ]; then
  echo "$CRED" | sed "s|$STAGE/$NAME/||" | sed 's/^/     /'
  FOUND=1
fi

# Real email addresses. example.* and .invalid are placeholders and allowed.
MAIL=$(grep -rnoE '[[:alnum:]._%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}' "$STAGE" 2>/dev/null |
       grep -viE '@example\.|@.*\.invalid|noreply@|@localhost' || true)
if [ -n "$MAIL" ]; then
  echo "$MAIL" | sed "s|$STAGE/$NAME/||" | sed 's/^/     /'
  FOUND=1
fi

# Anything that is not plain text has no business in an allowlist this small, and is
# how a client document would arrive if the list were edited carelessly.
BIN=$(find "$STAGE" -type f -exec sh -c 'file -b --mime "$1" | grep -q "charset=binary" && echo "$1"' _ {} \; 2>/dev/null || true)
if [ -n "$BIN" ]; then
  echo "$BIN" | sed "s|$STAGE/$NAME/||" | sed 's/^/     binary: /'
  FOUND=1
fi

[ "$FOUND" = 0 ] || die "the findings above would be sent to a customer.

  Remove them from the files, or take the file out of INCLUDE in this script. This is
  not a warning to click past: the repository already holds one client's government
  document, and the whole point of a bundle is that it does not travel."
ok "no addresses, credentials, real email addresses or binaries"

# Sanity: it must actually be installable.
for required in requirements.txt ocr/main.py deploy/install.sh; do
  [ -f "$STAGE/$NAME/$required" ] || die "bundle is missing $required"
done
grep -q "python-multipart" "$STAGE/$NAME/requirements.txt" ||
  die "requirements.txt has no python-multipart; the engine will not start"
grep -q "opencv-python-headless" "$STAGE/$NAME/requirements.txt" ||
  die "requirements.txt has no opencv-python-headless"
grep -qE '^opencv-python==' "$STAGE/$NAME/requirements.txt" &&
  die "requirements.txt still pins opencv-python; it needs libGL and will not import
  on a server" || true
ok "requirements look installable"

chmod +x "$STAGE/$NAME/deploy/install.sh"
mkdir -p "$OUT_DIR"
TARBALL="$(cd "$OUT_DIR" && pwd)/${NAME}.tar.gz"
tar -czf "$TARBALL" -C "$STAGE" "$NAME"
ok "$(du -h "$TARBALL" | cut -f1)  $TARBALL"

cat <<EOF

Send the customer two things:

  1. ${NAME}.tar.gz
  2. deploy/CUSTOMER-SETUP.md   (or just point them at the README inside)

They run:

    tar -xzf ${NAME}.tar.gz
    cd ${NAME}/deploy
    sudo ./install.sh --dms-server <YOUR_DMS_SERVER_IP> --source ..

Give them the DMS server IP separately. It is the only host allowed to reach their
engine, and it is not in this bundle on purpose.
EOF
