import { useState } from "react";

export function CopyBlock({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="copy-block">
      <pre tabIndex={0} aria-label={label}>{text}</pre>
      <button className="secondary" onClick={() => navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); })}>
        {copied ? "Copied" : "Copy"}</button>
    </div>
  );
}
