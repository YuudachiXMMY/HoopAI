# Setting up your laptop before our next session

**Estimated time: 60–90 minutes**

Hi! Before our next session, please install a few tools on your laptop. You don't need to understand what any of them do yet — just follow the steps in order and send me the final check at the bottom.

**Please start this at least a day early.** If something goes wrong, I'd rather fix it over a message than burn our session on installs.

---

## Before you start

**1. Which computer do you have?** Follow either the **Windows** section or the **Mac** section below — not both.

- Windows: look for the ⊞ Windows key on your keyboard.
- Mac: look for the ⌘ Command key.

**2. You'll need a ChatGPT account** (free is ok; best with a paid plan: Plus, Pro, or Edu) for the Codex step.

**3. Two words you'll see a lot:**

- **Terminal** — a window where you type commands instead of clicking. It looks intimidating; it isn't. You'll mostly paste things I give you.
- **Install** — in a terminal, software is installed by typing a command, not by double-clicking.

---

# WINDOWS

## Step 1 — Git (includes "Git Bash", your terminal)

1. Go to **https://git-scm.com/download/win** → click **"64-bit Git for Windows Setup"**. The download starts automatically.
2. Open the downloaded file. Click **Next** through the installer — the defaults are correct — **except** watch for these two screens:
   - **"Choosing the default editor used by Git"** → open the dropdown and pick **"Use Visual Studio Code as Git's default editor"**. (If it's not in the list, pick **Notepad** — we'll fix it later.)
   - **"Adjusting your PATH environment"** → make sure **"Git from the command line and also from 3rd-party software"** is selected (it's the default — just don't change it).
3. Click **Install**, then **Finish**.

**Verify:** Press the ⊞ Windows key, type `Git Bash`, press Enter. A black window opens. Type this and press Enter:

```
git --version
```

You should see something like `git version 2.5x.x.windows.1`. ✅

**Keep this Git Bash window open — it's the terminal you'll use for everything below.**

---

## Step 2 — Node.js

1. Go to **https://nodejs.org/en/download**
2. Download the **LTS** version (currently **24.22.0**). LTS = "Long Term Support" = the stable one. **Do not** download the version labeled "Current".
3. Run the installer, accept the license, click **Next** through everything, **Install**.
   - If it offers a checkbox for *"Automatically install the necessary tools…"*, **leave it unchecked**. You don't need it.

**Verify:** **Close Git Bash and open it again** (this matters — it won't see Node until you restart it). Then:

```
node --version
npm --version
```

You should see `v24.x.x` and a number like `11.x.x`. ✅

---

## Step 3 — Visual Studio Code (the editor)

1. Go to **https://code.visualstudio.com/** → click the big blue **Download for Windows** button.
2. Run the installer. Accept the agreement, click Next.
3. On the **"Select Additional Tasks"** screen, **check all of these**:
   - ☑ Add "Open with Code" action to Windows Explorer file context menu
   - ☑ Add "Open with Code" action to Windows Explorer directory context menu
   - ☑ **Add to PATH** ← this one is the important one
4. Install → Finish.

**Verify:** Close and reopen Git Bash, then:

```
code --version
```

You should see a version number like `1.10x.x`. ✅

---

## Step 4 — Python

1. Go to **https://www.python.org/downloads/** → click the yellow **Download Python 3.x.x** button.
2. Run the installer. **On the very first screen, before clicking anything else:**
   - ☑ **Check "Add python.exe to PATH"** at the bottom. ← **This is the #1 thing people miss.** If you skip it, nothing below will work.
3. Then click **Install Now**. At the end, if it offers **"Disable path length limit"**, click it.

**Verify:** Close and reopen Git Bash, then:

```
python --version
```

You should see `Python 3.1x.x`. ✅

> ⚠️ If you instead get a Microsoft Store window or an error, you missed the PATH checkbox. Re-run the installer, choose **Modify**, and make sure PATH is checked.

---

## Step 5 — Codex (the AI coding assistant)

In Git Bash, type:

```
npm install -g @openai/codex
```

This takes 1–3 minutes and prints a lot of text. That's normal. As long as the last lines don't say `ERR!`, you're fine.

**Verify & sign in:**

```
codex
```

It will ask you to sign in — choose **"Sign in with ChatGPT"** and press Enter. Your browser opens; log in there, then come back to Git Bash. It should say you're signed in.

Type `/quit` or press `Ctrl + C` twice to exit. ✅

---

## Step 6 — FFmpeg (video processing)

> 🟡 **This is the hardest step on Windows, and it's the one most likely to go wrong.**
> **If it doesn't work after one honest attempt, stop and bring it to our session — we'll do it together.** Everything else on this list is more important. Do not spend an hour on this.

FFmpeg is the tool that actually cuts video files. Unlike the others, it has no friendly installer.

### Try this first (the easy way)

1. Press the ⊞ Windows key, type `PowerShell`, and press Enter. **This is a different window from Git Bash** — blue instead of black. That's correct.
2. Paste this and press Enter:

   ```
   winget install -e --id Gyan.FFmpeg
   ```

3. If it asks you to agree to terms, type `Y` and press Enter.
4. Wait for it to finish, then **close PowerShell**.

**Verify:** Open a **brand new Git Bash window** (this won't work in one that was already open), then:

```
ffmpeg -version
```

You should see a wall of text starting with `ffmpeg version ...`. That's success — the text is supposed to look like that. ✅

### If that didn't work

Two common reasons, both fine:

- **`winget` is not recognized** → your Windows is too old for it (it needs Windows 10 version 1809 or newer). Skip to "bring it to the session" below.
- **It installed, but `ffmpeg -version` still says `command not found`** → this package is known to occasionally fail to register itself properly. Not your fault.

**Either way: stop here and bring it to our session.** Fixing this by hand means editing a Windows system setting called PATH, and it's much faster to do that together on a screen share than over messages. Just make a note that FFmpeg is the one that didn't work, and move on to the next section.

---

# 🍎 MAC

## Step 1 — Open Terminal and install Git

1. Press **⌘ + Space**, type `Terminal`, press Enter. A window opens — this is your terminal for everything below.
2. Type this and press Enter:

   ```
   git --version
   ```

3. A popup may appear saying *"The git command requires the command line developer tools"* → click **Install** and wait (5–10 min). If no popup appears and you just see a version number, Git is already there.

**Verify:**

```
git --version
```

You should see `git version 2.x.x`. ✅

---

## Step 2 — Homebrew (a tool that installs other tools)

Paste this into Terminal and press Enter:

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

- It will ask for your **Mac login password**. Type it and press Enter — **the characters won't appear as you type.** That's normal, not a bug. Just type it and hit Enter.
- Takes 5–15 minutes.
- **At the very end it prints 2–3 lines under "Next steps"** telling you to run some `echo`/`eval` commands. **Copy and run those lines exactly as printed.** Don't skip this.

**Verify:** Close Terminal, open it again, then:

```
brew --version
```

You should see `Homebrew 4.x.x`. ✅

---

## Step 3 — Node.js, Python, VS Code, Codex

Paste these one at a time, waiting for each to finish:

```
brew install node
```

```
brew install python
```

```
brew install --cask visual-studio-code
```

```
brew install --cask codex
```

---

## Step 4 — Enable the `code` command

1. Open **Visual Studio Code** from your Applications folder (if macOS warns it's from the internet, click **Open**).
2. Press **⌘ + Shift + P** — a search bar appears at the top.
3. Type `shell command` and click **"Shell Command: Install 'code' command in PATH"**.

**Verify:** Back in Terminal, close and reopen it, then `code --version` should print a version number. ✅

---

## Step 5 — Sign in to Codex

```
codex
```

Choose **"Sign in with ChatGPT"**, press Enter, log in via the browser that opens, then return to Terminal. Exit with `/quit` or `Ctrl + C` twice. ✅

---

## Step 6 — FFmpeg (video processing)

FFmpeg is the tool that actually cuts video files. On Mac this is genuinely easy — one command:

```
brew install ffmpeg
```

> ⏳ **This one is slow — 5 to 20 minutes**, and it prints a huge amount of text as it installs a long list of dependencies. That is normal. Leave it alone and let it finish; don't press `Ctrl + C`.

**Verify:**

```
ffmpeg -version
```

You should see a wall of text starting with `ffmpeg version ...`. That's success — the text is supposed to look like that. ✅

> 🟡 **If this fails, don't fight it — bring it to our session.** It's the one install on this list with the most moving parts, and it's faster to sort out together than over messages. Just note that FFmpeg is the one that didn't work and move on.

---

# 📁 GET THE PROJECT CODE

Now you'll download the project we'll be working on. This part works the **same on Windows and Mac** — just use your terminal (**Git Bash** on Windows, **Terminal** on Mac).

### Step 1 — Pick where it goes

We'll put it on your Desktop so it's easy to find. Paste this:

```
cd ~/Desktop
```

Nothing will appear to happen. That's correct — `cd` means "change directory", and it's silent when it works.

### Step 2 — Clone (download) the project

"Clone" is the Git word for downloading a project along with its full history. Paste this:

```
git clone https://github.com/YuudachiXMMY/HoopAI.git
```

You'll see a few lines about counting and receiving objects. It takes well under a minute.

> ℹ️ You don't need a GitHub account or a password for this — the project is public. If it asks you for a username or password, something's off: don't type anything, just send me a screenshot.

### Step 3 — Go into the project folder

```
cd HoopAI
```

**Verify** you're in the right place:

```
pwd
ls
```

- `pwd` ("print working directory") should end in `/Desktop/HoopAI`
- `ls` ("list") should show folders and files including `README.md`, `requirements.txt`, `ingest`, `detect`, `events`, and `clips`

If you see those, you're done. ✅

### Step 4 — Open it in VS Code

```
code .
```

That dot matters — it means "this folder". VS Code should open with the project's files listed down the left side.

> 🎉 **That's the finish line for the setup.** The two things below are optional.

---

### Optional — install the project's Python packages

Only try this if the steps above went smoothly and you're curious. **If anything here fails, skip it entirely** — we'll do it together, and it won't slow us down.

Make sure you're still in the `HoopAI` folder, then:

**Windows (Git Bash):**

```
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

**Mac (Terminal):**

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The first command makes a private, project-only space for Python packages so they can't interfere with anything else on your computer. After the second command your terminal prompt gets a `(.venv)` prefix — that's how you know it worked. The third downloads the project's packages, which takes several minutes and prints a lot of text.

### Heads-up: two things are *supposed* to be missing

So you don't think you did something wrong:

1. **There's no trained model file.** The project needs a file at `data/models/basketball.pt` that isn't included in the download (it's too large to store in Git). I'll give it to you in our session.
2. **There's no "run" button or main script.** This project is a set of building blocks, not a finished app — there's deliberately nothing to launch yet. That's what we'll be working on.

---

# ✅ FINAL CHECK — please do this and send me the result

Open your terminal (**Git Bash** on Windows / **Terminal** on Mac), paste the **entire block** for your system at once, and press Enter:

**Windows:**

```
echo "--- git ---";    git --version
echo "--- node ---";   node --version
echo "--- npm ---";    npm --version
echo "--- python ---"; python --version
echo "--- vscode ---"; code --version
echo "--- codex ---";  codex --version
echo "--- ffmpeg ---"; ffmpeg -version | head -1
echo "--- repo ---";   ls ~/Desktop/HoopAI/README.md
```

**Mac:**

```
echo "--- git ---";    git --version
echo "--- node ---";   node --version
echo "--- npm ---";    npm --version
echo "--- python ---"; python3 --version
echo "--- vscode ---"; code --version
echo "--- codex ---";  codex --version
echo "--- ffmpeg ---"; ffmpeg -version | head -1
echo "--- repo ---";   ls ~/Desktop/HoopAI/README.md
```

**Then send me a screenshot of the whole output.** Every section should show a version number, and the `repo` line should show a path ending in `README.md`. If any line says `command not found` or `No such file`, tell me which one — that's the only thing I need to know to help you.

**One exception:** if `ffmpeg` is the only thing that failed, that's acceptable — bring it to the session and we'll fix it there. Everything else should be working before we meet.

---

# 🆘 If you get stuck

| What you see | What to do |
|---|---|
| `command not found` right after installing | **Close the terminal completely and open a new one.** Fixes ~80% of cases. |
| Windows: `python` opens the Microsoft Store | You missed the "Add python.exe to PATH" checkbox — re-run the Python installer and choose **Modify**. |
| Mac: password typing shows nothing | Expected behavior. Type it anyway and press Enter. |
| `npm install` ends with red `ERR!` lines | Screenshot the last 15 lines and send them to me. Don't retry more than once. |
| **Anything at all with FFmpeg** | **Stop and bring it to the session.** Expected to be the sticky one — it's not worth your evening. |
| `git clone` asks for a username/password | Don't type anything. Send me a screenshot — the project is public, so it shouldn't ask. |
| `cd HoopAI` says "No such file or directory" | The clone didn't finish. Run `cd ~/Desktop` then try the `git clone` line again. |
| `pip install` fails in the optional step | Skip the optional step entirely. It changes nothing for our session. |
| An installer asks something not covered above | Take the default and tell me. Defaults are almost always right. |

**Three rules:**

1. Don't try to fix things by guessing or by pasting commands from random websites — message me instead, it's faster.
2. Don't worry about understanding *why* any of this works. That's what the session is for.
3. **There's no prize for suffering through a broken step alone.** If one thing won't cooperate after a real attempt, note which one, skip it, and bring it to our session. Showing up with five of six working is a good outcome.

See you then!