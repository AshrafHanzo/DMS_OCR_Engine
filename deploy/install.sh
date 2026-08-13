#!/usr/bin/env bash
#
# One-command installer for the DMS OCR engine (v3, PaddleOCR-VL via Ollama).
#
# WHY THIS EXISTS
#
# Setting this up by hand took roughly fifteen rounds of correction, and none of the
# failures were obvious ones. Two dependencies were missing from requirements.txt in
# ways that only surface at import; a Kannada font was absent, which fails AFTER a page
# has paid its full recognition cost; the workspace defaulted inside the git tree on the
# root disk; Ollama silently ran most of the model on the CPU. A customer's IT team
# should not have to rediscover any of that.
#
# Everything here is idempotent -- run it again safely.
#
# USAGE
#
#   sudo ./install.sh --dms-server <ip-of-the-DMS-app-server>
#
#   --dms-server IP   the ONLY host allowed to reach the engine port. Required unless
#                     --no-firewall is given: the engine has no authentication, so an
#                     open port means anyone can use the GPU and read back what they
#                     upload.
#   --dir PATH        install location            (default /opt/dms-ocr)
#   --data PATH       workspace + cache disk      (default largest non-root mount, else
#                                                  <dir>/workspace)
#   --port N          engine port                 (default 8080)
#   --user NAME       account to run as           (default the invoking sudo user)
#   --no-firewall     skip ufw. Only if something else already restricts the port.
#   --skip-model      do not pull the model (for an air-gapped box you will load later)
#   --source PATH     install from an unpacked bundle or tarball instead of cloning.
#                     Use this when you were sent a .tar.gz: the engine repository is
#                     private and holds client documents, so it is not clonable and must
#                     not be made public. From inside an unpacked bundle: --source ..

set -euo pipefail

DIR=/opt/dms-ocr
DATA=""
PORT=8080
RUN_USER="${SUDO_USER:-$(id -un)}"
DMS_SERVER=""
DO_FIREWALL=1
PULL_MODEL=1
SOURCE=""
REPO="https://github.com/AshrafHanzo/DMS_OCR_Engine.git"
MODEL="AuditAid/PaddleOCR-VL-1.6-0.9B"

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2 ;;
    --data) DATA="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --user) RUN_USER="$2"; shift 2 ;;
    --dms-server) DMS_SERVER="$2"; shift 2 ;;
    --no-firewall) DO_FIREWALL=0; shift ;;
    --skip-model) PULL_MODEL=0; shift ;;
    --source) SOURCE="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    # Print the USAGE block only, matched by content rather than by line number: a
    # hard-coded range drifts every time the header above it is edited, and the last
    # one left --help cut off mid-sentence.
    -h|--help) awk '/^# USAGE/{f=1} /^set -euo/{exit} f{sub(/^# ?/,""); print}' "$0"
               exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mok\033[0m   %s\n' "$*"; }
warn() { printf '   \033[33mwarn\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mstopped:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run with sudo"

# ── 1. preflight ─────────────────────────────────────────────────────────────
# Checked before anything is written, so a machine that cannot run this is rejected
# in seconds rather than after a 2GB download.
say "1. checking this machine"

. /etc/os-release 2>/dev/null || die "cannot read /etc/os-release"
case "${ID:-}:${VERSION_ID:-}" in
  ubuntu:22.04|ubuntu:24.04|debian:12) ok "$PRETTY_NAME" ;;
  *) warn "$PRETTY_NAME is untested; built and verified on Ubuntu 24.04" ;;
esac

[ "$(uname -m)" = x86_64 ] || die "$(uname -m) is not supported.

  Everything here was built and verified on x86_64 only. Nothing in this stack has been
  tested on aarch64, and an NVIDIA Jetson in particular ships an older JetPack CUDA
  stack with GPU memory shared with the system -- which is why the engine was moved off
  one. Whether it COULD work on ARM is untested, not established either way. Ask before
  attempting it rather than treating this refusal as proof it is impossible."

command -v python3 >/dev/null || die "python3 not found"
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 - <<'EOF' || die "python $PYV is too old; 3.10+ required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
EOF
ok "python $PYV"

id -u "$RUN_USER" >/dev/null 2>&1 || die "user '$RUN_USER' does not exist"
ok "will run as $RUN_USER"

# GPU. Not fatal -- the engine runs on CPU -- but the difference is so large that
# continuing silently would be misleading.
VRAM_MB=0
if command -v nvidia-smi >/dev/null 2>&1 &&
   VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1); then
  GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
  ok "$GPU_NAME, ${VRAM_MB} MiB"
  if [ "$VRAM_MB" -lt 4096 ]; then
    warn "under 4 GB: the model will NOT fit entirely on this card, so part of it runs
        on the CPU. Measured on a 2 GB Quadro P600: 189s per page. It works, it is just
        slow. 8 GB or more holds the whole model."
  fi
else
  VRAM_MB=0
  warn "no NVIDIA GPU detected. The engine will run entirely on the CPU, which is
        several times slower again than a small GPU. Usable for testing only."
fi

# Disk. The workspace and the recognition cache both grow; on / they take the machine
# down rather than just the engine.
if [ -z "$DATA" ]; then
  BEST=$(df -P --output=target,avail -x tmpfs -x devtmpfs 2>/dev/null | tail -n +2 |
         awk '$1 != "/" {print $2, $1}' | sort -rn | head -1 | awk '{print $2}')
  if [ -n "${BEST:-}" ]; then
    DATA="$BEST/dms-ocr"
    ok "data disk: $BEST (chosen as the largest non-root mount)"
  else
    DATA="$DIR/workspace"
    warn "no separate data disk found; using $DATA on the root filesystem. Pass --data
        to point somewhere with room, or the workspace will eventually fill /."
  fi
fi
AVAIL_GB=$(df -PBG "$(dirname "$DATA")" 2>/dev/null | tail -1 | awk '{gsub("G","",$4); print $4}')
[ "${AVAIL_GB:-0}" -ge 20 ] || die "only ${AVAIL_GB:-?} GB free at $DATA; need 20+"
ok "${AVAIL_GB} GB free for the workspace"

if ss -lntH "sport = :$PORT" 2>/dev/null | grep -q .; then
  # Our own engine holding the port is the UPGRADE case, not a conflict -- and refusing
  # it broke the idempotency this script promises: re-running on an installed machine
  # stopped here every time. It gets restarted at step 8 regardless.
  if systemctl is-active --quiet dms-ocr 2>/dev/null; then
    ok "port $PORT held by the existing dms-ocr service (this is an upgrade)"
  else
    HOLDER=$(ss -lntpH "sport = :$PORT" 2>/dev/null |
             grep -oE 'users:\(\("[^"]+"' | head -1 | sed 's/.*"\(.*\)"/\1/')
    die "port $PORT is in use by ${HOLDER:-another process}, which is not dms-ocr.

  Either stop it, or choose a different port with --port. Find it with:
      sudo ss -lntp \"sport = :$PORT\""
  fi
else
  ok "port $PORT is free"
fi

if [ "$DO_FIREWALL" = 1 ] && [ -z "$DMS_SERVER" ]; then
  die "--dms-server is required.

  The engine has NO authentication. Bound so the DMS server can reach it, anyone else
  who finds port $PORT can queue work on this GPU and read back whatever they upload.
  Give the DMS application server's IP so the port is opened only to it, or pass
  --no-firewall if something else already restricts it."
fi

# ── 2. system packages ───────────────────────────────────────────────────────
say "2. system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# Each of these fails LATE if missing, which is why they are all installed up front:
#  - tesseract + language packs: ocrmypdf is called with language=["kan","eng"]
#  - ghostscript: builds the searchable PDF
#  - the fonts: recognition SUCCEEDS, then rendering raises "no Kannada-capable font
#    found" -- so the page has already cost its full recognition time before failing
apt-get install -y -qq \
  python3-venv python3-dev build-essential git curl ca-certificates \
  tesseract-ocr tesseract-ocr-eng tesseract-ocr-kan \
  ghostscript fonts-lohit-knda fonts-noto-core >/dev/null
ok "tesseract $(tesseract --version 2>&1 | head -1 | awk '{print $2}'), ghostscript $(gs --version), Kannada fonts"

# ── 3. the code ──────────────────────────────────────────────────────────────
say "3. engine code -> $DIR"
if [ -n "$SOURCE" ]; then
  # From a bundle. This is the normal path for a customer: the repository is private
  # and contains client documents, so it is neither clonable nor safe to publish.
  mkdir -p "$DIR"
  if [ -f "$SOURCE" ]; then
    case "$SOURCE" in
      *.tar.gz|*.tgz) tar -xzf "$SOURCE" -C "$DIR" --strip-components=1 ;;
      *) die "--source must be a directory or a .tar.gz" ;;
    esac
    ok "unpacked $(basename "$SOURCE")"
  elif [ -d "$SOURCE" ]; then
    # Copying a directory onto itself makes cp refuse with "are the same file" and, under
    # set -e, aborts the whole install. Easy to hit: --source .. --dir <the same tree>.
    if [ "$(cd "$SOURCE" && pwd -P)" = "$(cd "$DIR" && pwd -P)" ]; then
      ok "source and install directory are the same; nothing to copy"
    else
      # -a to keep the executable bit on install.sh; trailing /. so the CONTENTS are
      # copied rather than the directory nesting one level deeper.
      cp -a "$SOURCE/." "$DIR/"
      ok "copied from $SOURCE"
    fi
  else
    die "--source not found: $SOURCE"
  fi
  [ -f "$DIR/requirements.txt" ] && [ -f "$DIR/ocr/main.py" ] ||
    die "that does not look like an engine bundle: requirements.txt and ocr/main.py
  are both expected at the top level of $DIR"
elif [ -d "$DIR/.git" ]; then
  # A local edit or a diverged branch makes --ff-only fail, and under set -e that ends
  # the run with git's message and no context. Say what it means and carry on with the
  # code already there: a re-run is usually about re-checking the machine, not the code.
  if git -C "$DIR" pull --ff-only -q 2>/dev/null; then
    ok "updated existing checkout"
  else
    warn "could not fast-forward $DIR (local changes, or a diverged branch).
        Continuing with the code already there. Resolve it with:
            git -C $DIR status"
  fi
else
  mkdir -p "$(dirname "$DIR")"
  git clone -q "$REPO" "$DIR" 2>/dev/null && ok "cloned" || die "could not clone $REPO.

  That repository is PRIVATE, and stays private because it contains client documents.
  If you were sent a .tar.gz, install from it instead:
      sudo ./install.sh --dms-server <IP> --source /path/to/bundle.tar.gz"
fi
chown -R "$RUN_USER":"$RUN_USER" "$DIR"

say "4. python dependencies"
[ -x "$DIR/venv/bin/python" ] || sudo -u "$RUN_USER" python3 -m venv "$DIR/venv"
sudo -u "$RUN_USER" "$DIR/venv/bin/pip" install -q --upgrade pip >/dev/null
sudo -u "$RUN_USER" "$DIR/venv/bin/pip" install -q -r "$DIR/requirements.txt"
ok "installed"
# Prove the app actually imports. Both dependencies that were once missing from
# requirements.txt failed exactly here, at import, and not before.
sudo -u "$RUN_USER" bash -c "cd '$DIR/ocr' && '$DIR/venv/bin/python' -c 'import main'" \
  >/dev/null 2>&1 && ok "the engine imports cleanly" \
  || die "the engine failed to import. Run this to see why:
  cd $DIR/ocr && $DIR/venv/bin/python -c 'import main'"

# ── 5. Ollama and the model ──────────────────────────────────────────────────
say "5. Ollama"
if command -v ollama >/dev/null 2>&1; then
  ok "already installed ($(ollama --version 2>/dev/null | head -1))"
else
  curl -fsSL https://ollama.com/install.sh | sh >/dev/null 2>&1
  ok "installed"
fi

# Tuned to the card actually present. The defaults assume a large GPU: on a small one
# the KV cache is what pushes the model off the card, so the context is cut and the
# cache quantised instead of leaving it to fail slowly.
if   [ "$VRAM_MB" -ge 8192 ]; then NPAR=2; CTX=4096; KV=f16
elif [ "$VRAM_MB" -ge 4096 ]; then NPAR=1; CTX=4096; KV=q8_0
else                               NPAR=1; CTX=2048; KV=q8_0
fi
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf <<EOF
# Written by dms-ocr install.sh for a ${VRAM_MB} MiB card. Re-run the installer after
# changing the GPU; these values are chosen from the VRAM it detects.
[Service]
# Keep the model resident. Without this Ollama unloads it after five minutes idle and
# the next page pays the whole load cost again.
Environment="OLLAMA_KEEP_ALIVE=-1"
# Concurrent requests. More than one context has to FIT; on a small card the failure
# is thrashing or an OOM kill partway through a page, not a clean error.
Environment="OLLAMA_NUM_PARALLEL=${NPAR}"
# The engine sends one crop at a time and caps output at 512 tokens, so a large window
# buys nothing and its KV cache is what evicts the model from the GPU.
Environment="OLLAMA_CONTEXT_LENGTH=${CTX}"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=${KV}"
EOF
systemctl daemon-reload
systemctl enable -q --now ollama
systemctl restart ollama
sleep 3
ok "tuned for ${VRAM_MB} MiB: parallel=${NPAR}, context=${CTX}, kv=${KV}"

if [ "$PULL_MODEL" = 1 ]; then
  say "6. the model (~1.8 GB)"
  if ollama list 2>/dev/null | grep -q "${MODEL%%:*}"; then
    ok "already present"
  else
    ollama pull "$MODEL"
    ok "pulled $MODEL"
  fi
else
  warn "--skip-model: load $MODEL yourself before the engine can read anything"
fi

# ── 7. workspace ─────────────────────────────────────────────────────────────
say "7. workspace -> $DATA"
mkdir -p "$DATA/workspace" "$DATA/cache"
chown -R "$RUN_USER":"$RUN_USER" "$DATA"
ok "created"

# ── 8. the service ───────────────────────────────────────────────────────────
say "8. service"
cat > /etc/systemd/system/dms-ocr.service <<EOF
[Unit]
Description=DMS OCR Engine v3 (PaddleOCR-VL via Ollama)
After=network-online.target ollama.service
Wants=network-online.target
# Requires, not Wants: without Ollama the engine still starts and answers /health, but
# returns EMPTY TEXT for every page. A silent wrong answer is worse than not starting.
Requires=ollama.service

[Service]
Type=simple
User=${RUN_USER}
Group=${RUN_USER}
# MUST be ocr/. main.py imports its siblings flat (from aligned_pipeline import ...),
# so starting from the repo root dies with ModuleNotFoundError: docx_generator.
WorkingDirectory=${DIR}/ocr
Environment="OCR_WORK_DIR=${DATA}/workspace"
Environment="OCR_CACHE_DIR=${DATA}/cache"
Environment="OCR_WORK_TTL_HOURS=24"
Environment="OCR_WORKERS=3"
# --workers 1 is required, not tuning: the recognition cache loads once per process, so
# a second worker keeps its own copy and they overwrite each other's file.
ExecStart=${DIR}/venv/bin/python -m uvicorn main:app \\
          --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 65
Restart=always
RestartSec=5
# A page can take minutes on a small card; the default stop timeout would kill a
# request mid-flight on restart and the page would be recorded as failed.
TimeoutStopSec=300
StandardOutput=journal
StandardError=journal
SyslogIdentifier=dms-ocr

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable -q dms-ocr
systemctl restart dms-ocr
ok "dms-ocr enabled and started"

# ── 9. firewall ──────────────────────────────────────────────────────────────
if [ "$DO_FIREWALL" = 1 ]; then
  say "9. firewall"
  apt-get install -y -qq ufw >/dev/null
  ufw allow OpenSSH >/dev/null
  ufw allow from "$DMS_SERVER" to any port "$PORT" proto tcp >/dev/null
  ufw --force enable >/dev/null
  ok "port $PORT reachable only from $DMS_SERVER"
  # Ollama is left alone deliberately: it listens on localhost, and the engine reaches
  # it there. Exposing 11434 would hand out unauthenticated model access.
  ok "Ollama left on localhost only"
else
  warn "firewall skipped. Port $PORT has no authentication in front of it."
fi

# ── 10. verify ───────────────────────────────────────────────────────────────
say "10. verifying (this runs a real page; minutes on a small card)"
cd "$DIR"
if sudo -u "$RUN_USER" "$DIR/venv/bin/python" verify_deploy.py \
     --url "http://localhost:$PORT" --cold; then
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  cat <<EOF

$(printf '\033[32m')The engine is installed and working.$(printf '\033[0m')

Give this to whoever administers your DMS:

    http://${IP:-<this-server-ip>}:${PORT}/process/text

They add it in the super admin portal under Setting -> OCR, press Test, then assign
your organisation to it. Nothing is routed here until they do.

  status   systemctl status dms-ocr
  logs     journalctl -u dms-ocr -f
  recheck  $DIR/venv/bin/python $DIR/verify_deploy.py --cold
EOF
else
  die "the engine is installed but verification failed. The output above says which
  check, and each one names what to do. Re-run:
    $DIR/venv/bin/python $DIR/verify_deploy.py --cold"
fi
