import { ReactNode } from "react";
import { OnboardingDoc } from "../api";
import { CopyBlock } from "./CopyBlock";

// Beside Getting started (B-075): what each step needs outside this page, and how to run Commerce OS. Nothing here
// takes a credential. The commands repeat INSTALL.md, and tests/test_onboarding.py holds the two together.
const GUIDE = "https://github.com/godesign27/commerce-os/blob/main/INSTALL.md";

function External({ href, children }: { href: string; children: ReactNode }) {
  return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
}

function Trouble({ children }: { children: ReactNode }) {
  return <><h4>If it goes wrong</h4>{children}</>;
}

function LoginHelp({ provider }: { provider: string | null }) {
  return (
    <>
      {provider === "supabase" ? (
        <ol>
          <li>Sign in to Supabase and open your store's project.</li>
          <li>Open <strong>SQL Editor</strong>, paste the script from this step and run it.</li>
          <li>Open <strong>Connect</strong>, then <strong>Session pooler</strong>, and copy the host.</li>
          <li>Find your project ref in the address bar, after <code>/project/</code>.</li>
          <li>Fill those and the script's password into the login's pattern, then enter it here.</li>
        </ol>
      ) : (
        <ol>
          <li>Sign in to your database's console and open your store's database.</li>
          <li>Open its <strong>SQL Editor</strong>, paste the script from this step and run it. On Neon, don't use the Roles page.</li>
          <li>Copy the host and database name from its connection details.</li>
          <li>Fill those and the script's password into the login's pattern, then enter it here.</li>
        </ol>
      )}
      <Trouble>
        <ul>
          <li><strong>Couldn't connect:</strong> check the host and password{provider === "supabase" && <>, and that the username is <code>commerce_os_read.</code> followed by your project ref</>}.</li>
          <li><strong>The script says the role already exists:</strong> you've run it before. Use that password, or change it in the SQL Editor.</li>
          <li><strong>Isn't safe to use:</strong> the login can do more than read the catalog. Use only the login this script creates.</li>
        </ul>
      </Trouble>
    </>
  );
}

function helpFor(id: string, doc: OnboardingDoc): ReactNode {
  if (id === "store") return (
    <>
      <p>You'll need your store's name and where its database is. If you're not sure where it is, ask whoever built the store.</p>
      <p>Choosing here doesn't connect to anything yet.</p>
    </>);
  if (id === "login") return <LoginHelp provider={doc.store.provider} />;
  if (id === "check") return (
    <>
      <p>There's nothing to prepare. Commerce OS reads your store's products, categories and tags, and changes nothing.</p>
      <Trouble><p><strong>The structure doesn't fit:</strong> your store's tables differ from what Commerce OS knows how to work with. The message names what's missing, so pass it to whoever built the store.</p></Trouble>
    </>);
  if (id === "mapping") return (
    <>
      <p>These lists come from your store, so nothing here creates a category or tag.</p>
      <p>Missing something? Add it in your store, then run <strong>Check the store</strong> again.</p>
    </>);
  if (id === "key") return (
    <>
      <ol>
        <li>Sign in at <External href="https://console.anthropic.com">console.anthropic.com</External>.</li>
        <li>Make sure the account has credit.</li>
        <li>Create an API key and copy it. You may only be able to see it once.</li>
        <li>Paste it here.</li>
      </ol>
      <Trouble><p><strong>It was refused:</strong> it may be incomplete or switched off. Create a new key and try again.</p></Trouble>
    </>);
  if (id === "voice") return <p>You don't need any accounts for this. You'll answer questions about your work, and you can change the answers later.</p>;
  if (id === "photos") return (
    <>
      <p>Put one photo per piece in the <code>inbox</code> folder inside your Commerce OS folder.</p>
      <p>Use JPEG, HEIC, PNG, WebP or TIFF, up to 100 MB each.</p>
    </>);
  return null;
}

export function StepHelp({ id, doc }: { id: string; doc: OnboardingDoc }) {
  return <div className="gs-help small">{helpFor(id, doc)}</div>;
}

export function InstallHelp() {
  return (
    <section className="gs-install small" aria-labelledby="gs-install">
      <h2 id="gs-install">Installation</h2>
      <p>You're seeing this page, so Commerce OS is installed. You won't need to install it again on this computer.</p>
      <h4>Start it again</h4>
      <p>In Terminal, from your Commerce OS folder:</p>
      <CopyBlock text="./start.sh" label="Command that starts Commerce OS" />
      <h4>Stop it</h4>
      <p>Press Ctrl-C in its Terminal window.</p>
      <h4>Update it</h4>
      <p>Stop it, then run:</p>
      <CopyBlock text="git pull" label="Command that downloads the latest version" />
      <p>Then start it again.</p>
      <h4>Install on another computer</h4>
      <p>Your logins and work stay on this computer, so a new copy starts empty.</p>
      <CopyBlock text="cd ~ && git clone https://github.com/godesign27/commerce-os.git && cd commerce-os" label="Command that downloads Commerce OS" />
      <CopyBlock text="./start.sh --check" label="Command that checks what the computer needs" />
      <p><External href={GUIDE}>Read the full install guide</External></p>
    </section>
  );
}
