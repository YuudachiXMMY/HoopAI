# Using HoopAI

**https://hoopai.ithacateens.com**

Upload a video of a game, get back a short clip of every basket.

**Estimated time to your first clip: 15 minutes**, most of which is the server
watching your video.

There are two halves to this guide. **Part 1 is for everyone.** Part 2 is only
for the one or two people who look after the server — if nobody has handed you
an SSH key, you don't need it and you can stop at the end of Part 1.

---

# Part 1 — Using HoopAI

## What it does

You give it a video. It looks at every frame, finds the moments the ball goes
through the hoop, and cuts a clip around each one — a few seconds before, a
couple after. You get the clips back.

It is not magic and it is not always right. It misses baskets, and sometimes it
calls something a basket that wasn't. That's normal and it is the interesting
part of the project.

## Two ways to use it

**The clicking way** (start here): open
**https://hoopai.ithacateens.com/docs** in any browser. That's an interactive
page listing everything HoopAI can do, with a **Try it out** button on each
one. You can do everything in this guide without touching a terminal.

**The typing way**: the `curl` commands below. Useful once you're writing code
that talks to HoopAI, which you will be.

Both do exactly the same thing. Pick whichever you like.

---

## Step 1 — Make an account

Anyone can sign up; there is no invite code. Your password must be **at least
10 characters**.

In the browser: go to `/docs`, find **POST /auth/signup**, click **Try it out**,
fill in your email and password, click **Execute**.

In a terminal:

```bash
curl -X POST https://hoopai.ithacateens.com/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"your-password-here"}'
```

You'll get back something like:

```json
{"token":"eyJhbGciOiJIUzI1NiIs...","email":"you@example.com"}
```

**That `token` is how HoopAI knows it's you.** Copy it somewhere — you need it
for every command below.

A few things about the token:

- It **expires after 12 hours**. When it stops working, that's why. Log in
  again (next step) to get a fresh one.
- Treat it like a password. Anyone holding it can act as you.
- Don't paste it into a group chat, a screenshot, or a commit.

## Step 2 — Logging in again

Once your token expires:

```bash
curl -X POST https://hoopai.ithacateens.com/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"your-password-here"}'
```

Same shape of response, new token.

> If you get the password wrong **10 times**, the account locks for 15 minutes
> and tells you how long is left. This is here to stop someone guessing their
> way into other people's accounts — it is not a punishment, just wait it out.

## Step 3 — Save your token to a variable

This saves retyping it. In your terminal:

```bash
TOKEN='paste-your-token-here'
```

(Only lasts until you close the terminal window. Just run it again next time.)

## Step 4 — Upload a video

```bash
curl -X POST https://hoopai.ithacateens.com/video/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F 'file=@/path/to/your/game.mp4'
```

Replace `/path/to/your/game.mp4` with the real path. On a Mac you can drag the
file into the terminal window and it fills the path in for you.

You get back:

```json
{"job_id":"3fa85f64-5717-4562-b3fc-2c963f66afa6","status":"pending"}
```

**Copy the `job_id`.** That's how you check on it.

### What it will and won't accept

| | |
|---|---|
| File types | `.mp4` `.mov` `.m4v` `.avi` `.mkv` `.webm` |
| Largest file | 512 MB |
| Smallest file | 1 KB (an empty file is rejected) |
| Videos you can keep | 50 at a time |

If you hit the 50 limit, ask an instructor to clear some out.

### "Too many videos are being processed right now"

You'll see this when other people are ahead of you. HoopAI deliberately
processes **one video at a time**.

That's not laziness. Finding baskets means running a neural network over every
single frame, which pins a CPU core for minutes. This server also runs the
school's website and several other applications, and if HoopAI were allowed to
start ten of those at once, it would take all of them down with it. So it
queues, and when the queue is full it says no instead of falling over.

Wait a couple of minutes and upload again.

## Step 5 — Check on your video

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://hoopai.ithacateens.com/video/results/YOUR_JOB_ID
```

The `status` moves through:

| Status | Meaning |
|---|---|
| `pending` | Waiting its turn in the queue |
| `processing` | Being watched right now |
| `done` | Finished — `clips` lists what it found |
| `error` | Something went wrong; `error` says what |

When it's `done`:

```json
{
  "job_id": "3fa85f64-...",
  "status": "done",
  "basket_count": 7,
  "clips": ["basket_01.mp4", "basket_02.mp4", "..."],
  "error": null
}
```

**How long does it take?** Roughly as long as the video, often longer. A
5-minute game can be 10+ minutes. Check back rather than sitting on it.

`"basket_count": 0` with `"status": "done"` means it genuinely found nothing —
not that it broke. Try a clip where the hoop is clearly visible.

## Step 6 — Download your clips

One at a time, by name, from the `clips` list:

```bash
curl -H "Authorization: Bearer $TOKEN" -O \
  https://hoopai.ithacateens.com/video/results/YOUR_JOB_ID/clips/basket_01.mp4
```

The `-O` saves it with the same filename in whatever folder you're in.

## Step 7 — See everything you've uploaded

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://hoopai.ithacateens.com/video/jobs
```

Your 50 most recent, newest first.

---

## You can only see your own videos

Every request checks who you are and shows you only your own work. If you try
another person's `job_id` you get **`404 Job not found`** — the same answer you
get for an id that doesn't exist at all.

That's on purpose. If it said "403 Forbidden" instead, that would quietly
confirm the id was real, and you could go fishing for other people's work just
by trying ids. Answering identically either way means there is nothing to
learn by guessing.

So: your footage is yours. And you can't see anyone else's, including by
accident.

---

## When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `401 {"detail":"Invalid or expired token."}` | Token is over 12 hours old, or mistyped | Log in again |
| `401 {"detail":"Not authenticated"}` | You forgot the `Authorization` header entirely | Add `-H "Authorization: Bearer $TOKEN"` |
| `422 String should have at least 10 characters` | Password too short at signup | Pick a longer one |
| `422` on signup, mentioning `email` | Not a valid email address | Check for typos |
| `409 That email is already registered.` | You already have an account | Log in instead |
| `415 Unsupported file type` | Not a video extension it accepts | Convert it, or check the file name |
| `413 Video exceeds the 512 MB limit` | File too big | Trim it, or export at lower quality |
| `400 That file is empty or too small` | The file didn't upload properly | Check the path — a typo gives an empty upload |
| `409 You already have 50 videos stored` | At your limit | Ask an instructor to clear some |
| `429 Too many videos being processed` | Queue is full | Wait a few minutes |
| `429 Too many failed attempts` | 10 wrong passwords | Wait 15 minutes |
| `404 Job not found` | Wrong id, or it isn't yours | Check `/video/jobs` for your real ids |
| `status: error` | Processing failed | Tell an instructor the `job_id` — the details are in the server log, not in your response |

That last row is deliberate: error messages shown to you are kept vague on
purpose, because detailed ones leak information about the server. An instructor
can read the real reason with `ops logs`.

---

## Things worth knowing

**Your uploads are kept.** Nothing deletes them automatically. Don't upload
anything you wouldn't want an instructor to see.

**Your password is stored safely** (hashed with argon2id), so nobody — not even
an instructor — can read it back. If you forget it, there is no reset flow yet;
an instructor has to clear the account.

**Anyone on the internet can sign up.** There's no invite code, so don't treat
this as private. If that becomes a problem we'll add one.

---
---

# Part 2 — For maintainers only

**Skip this unless someone handed you an SSH key.** This section is for the one
or two people who deploy HoopAI to the server.

## What you've been given

A private key file, probably called `hoopai-restricted`. It logs you into the
server, but into a **deliberately narrow set of commands** — you can ship code
and read logs, and you cannot read the application's secrets or open a shell
inside the container.

That narrowness is not distrust. The server runs the school website and several
other applications, and the fewer things any one key can do, the less an
accident or a lost laptop costs.

## Setting it up

Save the key as `~/.ssh/hoopai` and lock its permissions — SSH refuses to use a
key other people on your machine could read:

```bash
chmod 600 ~/.ssh/hoopai
```

Add this to `~/.ssh/config` (create the file if it doesn't exist):

```
Host hoopai
    HostName 2.24.197.12
    User app-hoopai
    IdentityFile ~/.ssh/hoopai
```

Test it:

```bash
ssh hoopai 'ops status'
```

You should see the running containers and the commit currently deployed.

Connecting with no command at all prints exactly what your key may run:

```bash
ssh hoopai
```

## What you can run

| Command | What it does |
|---|---|
| `ops status` | Container status and the deployed commit |
| `ops logs` | Recent logs. `-f` to follow, `-n 50` for 50 lines, `api` for one service |
| `ops deploy` | Pull the latest `prod`, rebuild, restart |
| `ops restart` | Restart without rebuilding |
| `ops rollback` | Go back to the previous commit |
| `ops version` | Version info |

Examples:

```bash
ssh hoopai 'ops logs -n 100 api'
ssh hoopai 'ops logs -f'
ssh hoopai 'ops deploy'
```

## What you can't run, and why

These are refused before they reach the server's tooling:

| Blocked | Why |
|---|---|
| `ops env`, `ops env-edit` | They print the application's `.env`, which holds the key HoopAI signs login tokens with. Anyone holding it can forge a session as any student, including an instructor. |
| `ops shell` | A shell inside the running container. |
| `ops backup`, `ops restore` | `restore` overwrites live data from a file the caller chooses. |
| Anything not starting with `ops` | There is no general shell on this key. |
| Chained commands (`;`, `&&`, `|`, `$(...)`) | Rejected outright rather than parsed. |

If you genuinely need one of these, ask the server operator. Don't look for a
way around it — the restriction is enforced by a file on the server that your
account cannot edit, so there isn't one.

## The deploy workflow

```
  You work on a branch
        ↓
  Open a pull request into `main`
        ↓
  An instructor reviews and merges          ← code review happens here
        ↓
  An instructor promotes `main` → `prod`    ← release happens here
        ↓
  ssh hoopai 'ops deploy'                   ← you can do this part
        ↓
  ssh hoopai 'ops status'      (confirm healthy)
```

**`ops deploy` builds whatever is on the `prod` branch right now.** It does not
review anything and it does not ask. The two gates above it — review, and the
promotion to `prod` — are what make it safe, and both belong to an instructor.

So `ops deploy` is not "push my code live". It is "the approved code is ready,
go fetch it".

### If a deploy goes wrong

```bash
ssh hoopai 'ops status'          # are the containers up and healthy?
ssh hoopai 'ops logs -n 200'     # what did it say on the way down?
ssh hoopai 'ops rollback'        # back to the previous commit
```

`rollback` reverts the **code**. It does not revert the database. Nothing in
HoopAI changes the database shape today, so this is safe — but say so to an
instructor before relying on it if that ever changes.

### After every deploy, check it actually works

```bash
curl https://hoopai.ithacateens.com/health
```

Expect `{"status":"ok","queue_depth":0,"queue_size":8}`. A healthy container is
not the same thing as a working application; this endpoint is the cheapest way
to tell the difference.

## Looking after the key

- **Never commit it.** Not to this repository, not to any repository.
- **Never send it over chat or email.** Those keep history, backups, and search
  indexes, and this key deploys to production.
- If you think it leaked — lost laptop, wrong chat window, pasted in a
  screenshot — **tell the server operator the same day**. Rotating it is a
  small job; finding out later is not.
- When you stop maintaining HoopAI, say so, so the key can be replaced.

---

## Getting help

- **Using HoopAI** (Part 1) — ask in the class channel; someone has hit it before.
- **Something looks broken for everyone** — tell an instructor, with the
  `job_id` if you have one.
- **Deploys and the server** (Part 2) — ask the server operator. Don't
  experiment on production to find out.
