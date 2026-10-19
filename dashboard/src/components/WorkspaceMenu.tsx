import { useState } from "react";
import { CircleHelp, KeyRound, LogOut } from "lucide-react";

import type { Me } from "@/api/auth";
import { initials } from "@/lib/initials";

import { PenDialog } from "./PenDialog";

export function WorkspaceMenu({
  me,
  onHelp,
  onTokens,
  onSignOut,
}: {
  me: Me;
  onHelp: () => void;
  onTokens: () => void;
  onSignOut: (forgetBrowser: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const mark = initials(me);
  const run = (action: () => void) => () => {
    setOpen(false);
    action();
  };
  return <>
    <button type="button" aria-label="Workspace menu" className="pen-avatar" onClick={() => setOpen(true)}>{mark}</button>
    <PenDialog open={open} onOpenChange={setOpen} title="Workspace menu" className="pen-workspace-menu">
      <div className="pen-workspace-identity"><span className="pen-avatar">{mark}</span><div><strong>{me.display_name ?? me.email ?? "Service access"}</strong><small>{me.email ?? "No personal account"}</small><small className="pen-workspace-name">{me.workspace.name}</small></div></div>
      <button type="button" onClick={run(onTokens)}><KeyRound aria-hidden="true" /><span>Developer tokens<small>API and CLI access</small></span></button>
      <button type="button" onClick={run(onHelp)}><CircleHelp aria-hidden="true" /><span>Help & shortcuts<small>Guides and key commands</small></span></button>
      <button type="button" className="pen-sign-out" onClick={run(() => onSignOut(false))}><LogOut aria-hidden="true" />Sign out</button>
      <button type="button" className="pen-sign-out" onClick={run(() => onSignOut(true))}>Sign out and forget this browser</button>
    </PenDialog>
  </>;
}
