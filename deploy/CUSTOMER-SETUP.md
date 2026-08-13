# Running the DMS OCR engine on your own server

This lets your documents be processed on hardware you control. Text extraction happens
on your machine; nothing about the document is sent anywhere else.

Hand this page to whoever administers your servers. It should take about 20 minutes,
most of that a download.

---

## 1. What the server needs

| | Minimum | Recommended |
|---|---|---|
| OS | Ubuntu 22.04 or 24.04, 64-bit **x86** | Ubuntu 24.04 |
| GPU | none (works, but slow) | **NVIDIA, 8 GB VRAM or more** |
| RAM | 8 GB | 16 GB |
| Disk | 40 GB free | 100 GB, ideally a second disk |
| Network | outbound HTTPS to install | plus one inbound port from the DMS server |

**The GPU is what decides speed.** The model needs about 2.5 GB of video memory. If it
does not fit, the remainder runs on the CPU and pages take minutes instead of seconds.

Measured by us, on one dense A4 page of Kannada text:

| Card | Model fits? | Per page |
|---|---|---|
| Quadro P600, 2 GB | no — 41% on GPU | **189 seconds** |
| 8 GB or more | yes | substantially faster |

We have not measured an 8 GB card ourselves, so we will not quote a figure we cannot
stand behind. What we can say is that the CPU portion is where nearly all of those 189
seconds go.

**x86 only.** Everything here was built and verified on x86_64; aarch64 is
untested, and the installer refuses it rather than half-working. That includes
NVIDIA Jetson boards, whose JetPack CUDA stack and shared GPU memory are why the
engine was moved off one. If ARM is your only option, ask us — it has not been
attempted, which is not the same as impossible.

## 2. Install

Four lines, run on the server itself. We will send you the exact command with the two
placeholders filled in.

```bash
curl -fL -o dms-ocr-engine.tar.gz <INSTALLER_URL>
tar -xzf dms-ocr-engine.tar.gz
cd dms-ocr-engine-*/deploy
sudo ./install.sh --dms-server <DMS_SERVER_IP> --source ..
```

`<INSTALLER_URL>` is a link on the DMS portal, so nothing needs emailing or copying
between machines — the server fetches it directly. The download is about 64 KB and
contains only the engine's own source; there is nothing confidential in it.

`<DMS_SERVER_IP>` is the address of the DMS application server. It becomes the **only**
machine allowed to reach your engine, because the engine has no password of its own.

That is the whole installation. The script checks the machine first and stops with a
plain explanation if something is missing, installs everything, tunes itself to the GPU
it finds, starts the service, closes the port to everyone else, and finishes by running
a real document through to prove it works.

Useful options:

```bash
sudo ./install.sh --dms-server <IP> --source .. --data /mnt/bigdisk   # workspace here
sudo ./install.sh --dms-server <IP> --source .. --port 9000           # if 8080 is taken
sudo ./install.sh --help
```

Re-running it is safe.

## 3. Send us one line

The installer prints an address when it finishes:

```
http://<your-server-ip>:8080/process/text
```

Send that to us. We add it in the DMS admin portal and assign your organisation to it.

**Until we do that, nothing changes** — your documents keep being processed exactly as
they are today. You can install this and take your time.

### One thing the installer cannot do for you

It configures the server's own firewall (`ufw`), and that is all it can reach. If the
machine sits behind anything else, that has to be opened too or the DMS server will never
get through:

| Where it runs | What else to open |
|---|---|
| AWS / Azure / GCP | the security group or network security group: inbound TCP 8080 from the DMS server's IP only |
| Behind a NAT router | a port-forward for TCP 8080 to this machine, restricted to that source IP if the router allows it |
| Corporate network | an inbound firewall rule from that one IP |

Restrict it to the DMS server's IP wherever you can. **The engine has no password of its
own** — anything that reaches the port can use your GPU and read back what it sends.

Check it from outside once open, and tell us the result either way:

```bash
curl -s -m 10 http://<your-server-ip>:8080/health
```

## 4. Afterwards

```bash
systemctl status dms-ocr          # is it running
journalctl -u dms-ocr -f          # what is it doing
sudo ./install.sh --dms-server <IP>   # re-run to update or re-check
```

To check it thoroughly at any time:

```bash
sudo /opt/dms-ocr/venv/bin/python /opt/dms-ocr/verify_deploy.py --cold
```

Run it with `sudo`: to measure a true cost per page it restarts the engine, which
clears the recognition cache the running process holds in memory. Without that the
timing is a cache hit, and it will say so rather than report a figure.

It reports every dependency separately, where the model is really running, whether
the workspace is on the right disk, and the current cost per page. It exits non-zero if
anything is genuinely wrong, so it is safe to run from a monitoring check.

## 5. Things worth knowing

**The engine has no password.** It is protected by the firewall rule the installer adds,
which allows only the DMS server. If you move the engine, change that rule — otherwise
anyone who finds the port can use your GPU and read back what they send it.

**The first page after a reboot is slower.** The model loads on first use.

**Repeat pages are nearly free.** Recognition results are cached by image content, so
re-processing the same page returns in about a second. That is a cache hit, not a
measure of speed.

**Disk use grows.** Per-page working files are deleted after 24 hours automatically. The
recognition cache is kept on purpose and grows slowly; it is safe to delete if you ever
need the space:

```bash
sudo systemctl stop dms-ocr
sudo rm -f <data-dir>/cache/.ocr_cache.json
sudo systemctl start dms-ocr
```

**To stop using it**, tell us and we will point your organisation back at the shared
engine. No documents or extracted text are affected — this only decides where *future*
pages are processed.

---

Anything unexpected: send the output of

```bash
sudo /opt/dms-ocr/venv/bin/python /opt/dms-ocr/verify_deploy.py --cold
journalctl -u dms-ocr -n 50 --no-pager
```

and we will tell you what it means.
