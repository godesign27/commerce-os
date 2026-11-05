# Install Commerce OS

These steps are for a Mac. You'll type a few commands into Terminal (in Applications → Utilities). After that,
the dashboard's Getting started page leads you through the rest.

Before you start, make sure you have:

- Access to your store's database, to create a read-only login. Commerce OS checks that login and refuses one
  that can change data or see customer tables.
- A Claude account with credit, for writing drafts ([console.anthropic.com](https://console.anthropic.com)).

## 1. Install Homebrew and Git

Follow the one-line install at [brew.sh](https://brew.sh). It also offers to install Apple's command line tools,
which include Git.

## 2. Download Commerce OS

This makes a `commerce-os` folder inside your home folder and moves into it:

```bash
cd ~ && git clone https://github.com/godesign27/commerce-os.git && cd commerce-os
```

## 3. Check this computer

```bash
./start.sh --check
```

This changes nothing. It lists what's missing and gives the exact command for each: `brew install python`,
`brew install node` or `brew install libpq`. Run those, then check again.

It may also suggest `brew install postgresql@16`. You only need that to publish to the local test store.

## 4. Start it

```bash
./start.sh
```

The first run takes a few minutes while it installs and builds. Your browser then opens
`http://127.0.0.1:8770`, where Getting started takes over. Only this computer can open that page.

Leave the Terminal window open while you work.

## Everyday use

| To | Do this |
|---|---|
| Stop it | Press Ctrl-C in its Terminal window |
| Start it again | Open Terminal, run `cd ~/commerce-os`, then `./start.sh` |
| Add photos | Put one photo per piece in the `inbox` folder inside `commerce-os` |
| Update it | Stop it, run `git pull`, then `./start.sh` |

## Your work stays on this computer

Your logins, store settings, drafts and approvals are in the `commerce-os` folder, and they don't go to GitHub.
Downloading Commerce OS again gives you a new, empty copy, so:

- **Back up the folder.** The hidden `.env` file in it holds your logins, so keep the backup private.
- **On a new computer,** follow these steps again, then go through Getting started again or restore your backup.

## Running a second copy

Each folder is its own copy, with its own logins, photos and listings. You could keep one for your store and
another for trying out changes. Download the second into a different folder:

```bash
cd ~ && git clone https://github.com/godesign27/commerce-os.git commerce-os-test && cd commerce-os-test
```

To run both at once, give the second its own port:

```bash
COMMERCE_OS_PORT=8771 ./start.sh
```

## If something goes wrong

- **`brew: command not found`:** Homebrew's installer ends by showing two commands that add it to your Terminal.
  Run those, then open a new Terminal window.
- **`Commerce OS is already running`:** it's open in another Terminal window, and the browser opens that copy.
- **The page won't open:** check that the Terminal window is still running, and look there for an error.
- **A different program is using port 8770:** start with another port, as in the command above.
