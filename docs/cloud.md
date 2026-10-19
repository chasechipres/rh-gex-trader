# Run it 24/7 on a free cloud server

The trader needs a session that stays open and a computer that stays awake. If you'd rather not leave your own
machine on, run it on an Oracle Cloud **Always Free** server instead. This is the high-level walkthrough; each
step names what to click or type, and the [README](../README.md) still covers the trader itself.

**You need:** everything in the README's [Quick start](../README.md#quick-start) (Robinhood agentic account, your subscription to the
source on X, a Claude Pro or Max plan, a GitHub account), plus a credit card for Oracle's identity check.
A domain and a free Cloudflare account are only needed if you also use the spare capacity for a [website](#extra-what-i-did-with-the-spare-capacity).

| | Cost |
|---|---|
| Oracle Cloud server (Ampere A1, Always Free) | $0, with the quota policy below so nothing billable can be created |
| Tailscale (Personal plan, only for the optional [browser desktop](#6-optional-the-desktop-in-any-browser)) | $0 |
| Cloudflare (DNS, proxy, SSL) | $0 |
| Claude plan, X subscription to the source | what you already pay |
| Domain | what you already pay (only for the optional website) |

> The server holds live logins: Claude, GitHub, X, and the Robinhood MCP connection to your agentic account.
> Keep SSH key-only, never open the remote-desktop port to the internet, and give the desktop user a strong
> password.

- [Let Claude drive the consoles](#let-claude-drive-the-consoles-optional) · [1. Oracle account](#1-oracle-account-and-a-0-guarantee) · [2. Create the server](#2-create-the-server)
- [3. Set up the server](#3-set-up-the-server) · [4. Start the trader](#4-start-the-trader) · [5. Day to day](#5-day-to-day)
  · [6. Optional: the desktop in any browser](#6-optional-the-desktop-in-any-browser)
- [Extra: what I did with the spare capacity](#extra-what-i-did-with-the-spare-capacity) · [Troubleshooting](#troubleshooting)

## Let Claude drive the consoles (optional)

Most of the clicking below (Oracle's console, Cloudflare's dashboard) can be done by Claude Code on your own
computer with the [drive-screen](https://github.com/coleam00/skills/tree/main/.claude/skills/drive-screen)
skill: it screenshots a window, clicks and types, and checks the screen after every action. Install it as a
global skill (copy that folder to `~/.claude/skills/drive-screen`), run
`python ~/.claude/skills/drive-screen/scripts/screenctl.py doctor` once, log in to Oracle and Cloudflare in
Chrome, then ask Claude to "use drive-screen to follow docs/cloud.md". What to expect:

- **You hand over the mouse and keyboard** while it runs; touching them corrupts the run. It says when it takes
  control and when it's done.
- **You type every password and 2FA code yourself.** Claude stops at login pages.
- **It asks before anything outward-facing or destructive** (creating a server, saving a policy, deleting DNS
  records). Claude Code's auto mode also blocks some of these on its own (DNS changes, for example); switch auto
  mode off with Shift+Tab and approve each step, or do that step by hand.
- **The terminal steps go over SSH instead,** which is faster and more reliable than driving a screen.

## 1. Oracle account and a $0 guarantee

1. **Sign up** at [oracle.com/cloud/free](https://www.oracle.com/cloud/free/). Pick a **home region** near you;
   it can't be changed, and Always Free servers only run there.
2. **Upgrade to Pay As You Go** (Billing → Upgrade and Manage Payment). Always Free resources stay free after
   the upgrade, and it gets you two things: A1 capacity is much easier to get, and Oracle doesn't reclaim idle
   servers (on free-only accounts, an instance that sits mostly idle for a week can be reclaimed).
3. **Add a quota policy** so nothing billable can be created, even by mistake. Identity & Security → Quota
   policies → Create, in the root compartment:

   ```
   zero compute-core quotas in tenancy
   zero compute-memory quotas in tenancy
   set compute-core quota standard-e2-micro-core-count to 2 in tenancy
   set compute-core quota standard-a1-core-count to 2 in tenancy
   set compute-memory quota standard-a1-memory-count to 12 in tenancy
   set compute-core quota standard-a1-core-regional-count to 2 in tenancy
   set compute-memory quota standard-a1-memory-regional-count to 12 in tenancy
   set block-storage quota total-storage-gb to 200 in tenancy
   set block-storage quota backup-count to 5 in tenancy
   set object-storage quota storage-bytes to 10000000000 in tenancy
   zero load-balancer quotas in tenancy
   set load-balancer quota lb-10mbps-micro-count to 1 in tenancy
   zero database quotas in tenancy
   zero filesystem quotas in tenancy
   zero vcn quota reserved-public-ip-count in tenancy
   ```

   The first two lines zero every compute shape; the rest allow back exactly the free amounts. Keep both A1
   pairs: the `-regional-count` lines are separate quotas, and without them creating an A1 server fails.
4. **Add a budget** (Billing → Budgets) of $1 with an alert at 1%. Budgets only email you; the quota policy
   is what actually blocks spending.

## 2. Create the server

Compute → Instances → Create instance:

| Setting | Value |
|---|---|
| Image | **Canonical Ubuntu 24.04** (the aarch64 build is picked to match the shape) |
| Shape | Ampere → **VM.Standard.A1.Flex**: **2 OCPU / 12 GB** for the trader alone, or **1 OCPU / 6 GB** to leave half spare for something else ([what I did with mine](#extra-what-i-did-with-the-spare-capacity)). The free total is 2 OCPU / 12 GB. |
| Networking | create a new VCN and public subnet; **assign a public IPv4 address** |
| SSH keys | **Generate a key pair** and download both keys (or paste your own public key) |
| Boot volume | default (about 47 GB; 200 GB total is free) |

The smaller E2.1.Micro shape (1 GB of memory) is too small for a desktop and Chrome. If A1 says **out of
capacity**, try again later or another availability domain.

Move the private key somewhere safe (`~/.ssh/oracle.key`), make it readable only by you (`chmod 600` on
macOS/Linux; on Windows, `icacls` to remove other users), then connect:

```sh
ssh -i ~/.ssh/oracle.key ubuntu@<public IP>
```

If there's no public IP on the instance page: the instance → Attached VNICs → the VNIC → IPv4 addresses →
Edit → Ephemeral public IP.

## 3. Set up the server

Over SSH, update it, set its clock to the time zone your `private/CLAUDE.md` names (cron uses the server's
clock; Eastern is the template's default), and install the tools, a lightweight desktop and Chrome:

```sh
export DEBIAN_FRONTEND=noninteractive               # so the upgrade doesn't stop on a config-file prompt
sudo -E apt update && sudo -E apt -y full-upgrade
sudo timedatectl set-timezone America/New_York     # or America/Chicago, America/Los_Angeles, ...
sudo -E apt install -y git gh gitleaks tmux xfce4 xfce4-goodies xrdp   # apt's gitleaks is older; the hook handles it
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -fsSL https://claude.ai/install.sh | bash
curl -fLo /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_arm64.deb
sudo -E apt install -y /tmp/chrome.deb
echo xfce4-session > ~/.xsession
sudo adduser xrdp ssl-cert && sudo systemctl enable --now xrdp
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target   # never suspend
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # swap, so a memory spike slows Chrome instead of killing it
sudo passwd ubuntu                                  # the remote-desktop login; make it strong
sudo reboot
```

`sudo passwd` asks for the password interactively, so run it in a real terminal, not through Claude Code's `!`
prefix (which has no terminal). The `~/.ssh/oracle.key` paths here are for macOS, Linux and bash; in Windows
PowerShell write `$HOME\.ssh\oracle.key`.

**Why a desktop:** the trader reads the source's posts in Chrome through Claude in Chrome, and the Robinhood MCP
login opens a browser. A remote desktop gives the server a real Chrome you can log in to once, and it keeps
running after you disconnect.

**Connect to the desktop** through an SSH tunnel (port 3389 stays closed to the internet):

```sh
ssh -i ~/.ssh/oracle.key -L 13389:localhost:3389 ubuntu@<public IP>
```

Leave that open, then point a Remote Desktop client at `localhost:13389` (Windows: Remote Desktop Connection;
macOS: Microsoft's Windows App) and log in as `ubuntu` with the password you set.

**Set up Chrome** in the desktop (Applications → Internet → Google Chrome). On first launch it asks you to create
a **keyring** password, which encrypts its saved logins: reuse the desktop password, and expect to unlock it once
after each reboot (leaving it blank skips the prompt but stores your X and Claude cookies unencrypted). Then add
the [Claude in Chrome](https://claude.com/chrome) extension and sign in to it with your Claude account, and log
in to **X** in the same browser.

## 4. Start the trader

In a terminal **inside the remote desktop** (so browser logins land in that Chrome), start a tmux session and
follow [Setup](setup.md#install):

```sh
tmux new -s trader
gh auth login --web --git-protocol https && gh auth setup-git
git config --global user.name "Your Name" && git config --global user.email "you@example.com"   # rhgex sync commits
gh repo clone chasechipres/rh-gex-trader && cd rh-gex-trader
claude                                     # then: /login, /chrome → Enabled by default, /setup
```

- **Log in with `/login`** using your Claude plan. Claude in Chrome doesn't work with an API key or a
  `claude setup-token` token.
- **`/setup`** detects Linux, checks the tools, and makes or clones your private folder (`--github` is the right
  choice here, so a lost server loses nothing). Already trading elsewhere? Have it clone your existing private
  repo rather than make a new one, so your limits, journal and exit plans come with you. Your account values
  (`private/state/account.json`) stay on the machine that made them, so the first cycle here asks for the agentic
  account's number once; ask Claude to look it up with the Robinhood tools instead of typing it. Its drawdown peak
  starts fresh on this machine.
- **`/setup` adds the `rhgex-start` alias** to `~/.bashrc`, which a terminal opened before `/setup` hasn't
  loaded: run `source ~/.bashrc` once there (new terminals and tmux windows pick it up on their own).
- **Then the steps only you can do:** `/mcp` → robinhood-trading → Authenticate (it opens in the desktop's
  Chrome), and confirm `/chrome` shows the extension connected.
- **Pin the session to the server's Chrome.** Claude in Chrome connects through your Claude account, so every
  Claude Code session you run sees every Chrome where the extension is signed in. If you also sign it in on your
  own computer, a session that hasn't picked one stops and asks which to use, and an unattended cycle can't
  answer. Tell the server's session "select the Linux browser for Claude in Chrome" after each start; once picked,
  it keeps using that one. Browser tasks from Claude Code on your own computer can likewise land in the server's
  Chrome: have them select your own browser, and keep them clear of the cycle times.
- **Start the day:** `/trading-day`. From then on the session schedules its own cycles each day, as on any
  machine. Use the [session-start command](running.md#using-more-than-one-machine) whenever you restart it.

Already trading on another computer? Hand off from it first ([Using more than one machine](running.md#using-more-than-one-machine)), and close
that session so both don't run exit checks.

## 5. Day to day

| To | Do |
|---|---|
| Check on it from anywhere (even a phone SSH app) | `ssh -i ~/.ssh/oracle.key ubuntu@<IP>`, then `tmux attach -t trader`; detach with **Ctrl+B, D** (never type `exit` there) |
| Watch Chrome or re-log in to X or Robinhood | the remote desktop, through the tunnel (or in a browser with [step 6](#6-optional-the-desktop-in-any-browser)) |
| Leave the remote desktop | close its window; **don't log out**, which closes Chrome and cuts off X and Claude in Chrome |
| Update | it updates itself each cycle; when it asks for a restart, exit `claude` and run the session-start command in the same tmux window |
| After a reboot (yours or Oracle maintenance) | remote desktop → open Chrome (unlock the keyring) → terminal → `tmux new -s trader` → `cd rh-gex-trader` → session-start command → pin the Linux browser → `/trading-day`. Resting stops protect positions meanwhile. |
| Track results | your private repo on GitHub, synced every cycle |

## 6. Optional: the desktop in any browser

The SSH tunnel needs an SSH client and a Remote Desktop app on every device, which is awkward on a phone.
[Apache Guacamole](https://guacamole.apache.org/) puts the same desktop in a browser tab, and
[Tailscale](https://tailscale.com/) (a private network between your own devices, free for personal use) makes it
reachable over HTTPS from your devices only. No port opens to the internet: the Oracle firewall still allows only SSH.

1. **Install Docker and Tailscale** over SSH:

   ```sh
   sudo apt install -y docker.io docker-compose-v2 && sudo usermod -aG docker ubuntu
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up --hostname=claude-box    # prints a login link: open it and approve the server
   ```

   Log out of SSH and back in so the `docker` group applies.
2. **In the [Tailscale admin console](https://login.tailscale.com/admin):** DNS → turn on **MagicDNS** and
   **HTTPS Certificates**; Machines → claude-box → ⋯ → **Disable key expiry** (otherwise the server drops off
   your network after 180 days).
3. **Run Guacamole** from `~/guacamole/docker-compose.yml`. Use 1.6.0 or later: the 1.5.x images have no ARM
   build for the A1 server.

   ```yaml
   services:
     guacd:
       image: guacamole/guacd:1.6.0
       network_mode: host               # reaches xrdp on 127.0.0.1:3389; nothing is published
       command: ["-b", "127.0.0.1"]     # passed on to guacd: listen on localhost only
       restart: unless-stopped
     guacamole:
       image: guacamole/guacamole:1.6.0
       network_mode: host
       depends_on: [guacd]
       environment:
         GUACAMOLE_HOME: /etc/guacamole-home
         CATALINA_OPTS: -Xmx256m          # keep Tomcat small: Chrome and Claude share this server
         WEBAPP_CONTEXT: ROOT             # serve at / instead of /guacamole/
       volumes:
         - ./home:/etc/guacamole-home:ro
       restart: unless-stopped
   ```

   `~/guacamole/home/guacamole.properties` holds two lines, `guacd-hostname: 127.0.0.1` and `guacd-port: 4822`.
4. **Set the web login** with `~/guacamole/set-password.sh` (`chmod +x` it, then run it yourself in a terminal).
   It stores only a SHA-256 hash of the password, and the desktop connection stores no password: xrdp asks for
   the `ubuntu` one.

   ```sh
   #!/bin/sh
   set -e
   cd "$(dirname "$0")"
   printf "Guacamole username: "; read -r user
   stty -echo; printf "Guacamole password (12+ chars): "; read -r pw; printf "\nAgain: "; read -r pw2; stty echo; echo
   [ "$pw" = "$pw2" ] || { echo "passwords differ"; exit 1; }
   [ ${#pw} -ge 12 ] || { echo "use at least 12 characters"; exit 1; }
   hash=$(printf %s "$pw" | sha256sum | cut -d' ' -f1)
   umask 077
   cat > home/user-mapping.xml <<XML
   <user-mapping>
     <authorize username="$user" password="$hash" encoding="sha256">
       <connection name="claude-box desktop">
         <protocol>rdp</protocol>
         <param name="hostname">127.0.0.1</param>
         <param name="port">3389</param>
         <param name="username">ubuntu</param>
         <param name="security">any</param>
         <param name="ignore-cert">true</param>
         <param name="color-depth">24</param>
         <param name="resize-method">display-update</param>
         <param name="enable-wallpaper">false</param>
       </connection>
     </authorize>
   </user-mapping>
   XML
   chmod 644 home/user-mapping.xml   # the container must read it; it holds only a hash
   docker compose restart guacamole >/dev/null 2>&1 || true
   ```

   **`color-depth` must match the desktop session that's already running** (24 here). xrdp keeps one session
   per user and color depth, so a match rejoins the desktop where Chrome runs; a mismatch starts a second,
   empty one.
5. **Start it and publish it on your tailnet:**

   ```sh
   cd ~/guacamole && docker compose up -d
   sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
   ```

   Both containers restart on their own after a reboot and use about 0.3 GB of memory. `tailscale serve status`
   shows the address, `https://claude-box.<your-tailnet>.ts.net/`.
6. **On each device** (Windows, Mac, phone), install Tailscale and sign in with the same account, open that
   address, log in, click **claude-box desktop**, and log in to xrdp as `ubuntu`.

- **Leave by closing the tab, never by logging out** of the desktop (logging out closes Chrome).
- **One viewer at a time:** opening it in Guacamole takes the desktop over from a connected Remote Desktop app,
  and the other way round. It's the same session either way.
- **Ctrl+Alt+Shift** opens Guacamole's menu: a clipboard box for copying text between your device and the
  desktop, an on-screen keyboard and display settings.
- Once Tailscale is up, SSH works over it too: `ssh -i ~/.ssh/oracle.key ubuntu@claude-box`.

## Extra: what I did with the spare capacity

This isn't part of the trader; skip it unless you want the same thing. Oracle's free A1 allowance is
2 OCPU / 12 GB, and giving the trader 1 OCPU / 6 GB leaves the other half unused. I used that half to host my
own website on my domain behind Cloudflare, at no extra cost. These are the steps if you want to do the same.
You need a domain whose nameservers point at Cloudflare (add the site in Cloudflare and change the
nameservers at your registrar) and a static page.

1. **Second server:** same settings as above, same VCN and subnet, 1 OCPU / 6 GB. Your existing key works for
   both.
2. **Open 80 and 443** in Oracle: Networking → your VCN → Security Lists → Default → Add ingress rule, source
   `0.0.0.0/0`, TCP, ports `80,443`. Ubuntu's own firewall on Oracle also blocks them, so on the server:

   ```sh
   sudo apt install -y nginx certbot python3-certbot-nginx iptables-persistent
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```

3. **Deploy:** copy your page to `/var/www/html/`, set `server_name example.com www.example.com;` in
   `/etc/nginx/sites-enabled/default`, then `sudo nginx -t && sudo systemctl reload nginx`.
4. **DNS in Cloudflare:** delete any old A, AAAA or CNAME records for `@` and `www` (a previous host's), then add
   `A @ → <server IP>` and `A www → <server IP>`, both **DNS only** (grey cloud) for now.
5. **HTTPS:** once `nslookup example.com 1.1.1.1` shows the server's IP, run
   `sudo certbot --nginx -d example.com -d www.example.com --redirect`. Certbot renews it automatically.
6. **Turn on Cloudflare:** SSL/TLS → Configure → **Full (strict)** and save, *then* switch both records to
   **Proxied** (orange cloud). In that order: proxying first, with the default mode, can cause a redirect loop.

## Troubleshooting

| Symptom | Fix |
|---|---|
| A1 creation fails with a quota or limit error | the `standard-a1-*-regional-count` lines are missing from the quota policy |
| A1 says out of capacity | retry later or in another availability domain; Pay As You Go accounts get capacity more easily |
| Remote desktop shows a black screen | `~/.xsession` must contain `xfce4-session`; log out of other desktop sessions for that user |
| `/chrome` says the extension isn't detected | Chrome must be running in the remote desktop, as the same user as `claude`; restart Chrome once after the first `/chrome` |
| A cycle skipped reading posts, asking which browser to use | the extension is signed in on another Chrome too; pin the session to the Linux browser (step 4) |
| Guacamole opens a second, empty desktop | its `color-depth` doesn't match the running session's; find that in `/var/log/xrdp.log` and set it in `set-password.sh`, then rerun it |
| The Guacamole address doesn't load | Tailscale must be connected on that device, with MagicDNS and HTTPS Certificates on in the admin console |
| Cycles run at the wrong times | `timedatectl` should show the zone `private/CLAUDE.md` names; change one to match the other |
| The website times out but `curl localhost` works on the server | check both the Oracle security list and the `iptables` rules |
| Cloudflare shows "too many redirects" | SSL/TLS mode isn't Full (strict) |
