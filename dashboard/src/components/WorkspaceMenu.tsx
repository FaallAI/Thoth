import { useState } from "react";
import { CircleHelp, LogOut, Settings, UserRound } from "lucide-react";
import { PenDialog } from "./PenDialog";

export function WorkspaceMenu({ onProfiles, onHelp }: { onProfiles: () => void; onHelp: () => void }) {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" aria-label="Workspace menu" className="pen-avatar" onClick={() => setOpen(true)}>MF</button>
    <PenDialog open={open} onOpenChange={setOpen} title="Workspace menu" className="pen-workspace-menu">
      <div className="pen-workspace-identity"><span className="pen-avatar">MF</span><div><strong>MF</strong><small>Personal workspace</small></div></div>
      <button type="button" onClick={() => { setOpen(false); onProfiles(); }}><UserRound aria-hidden="true" /><span>My profile<small>View creator profiles</small></span></button>
      <button type="button" disabled title="Account management is not available in this local workspace."><Settings aria-hidden="true" /><span>Account settings<small>Preferences & access</small></span></button>
      <button type="button" onClick={() => { setOpen(false); onHelp(); }}><CircleHelp aria-hidden="true" /><span>Help & shortcuts<small>Guides and key commands</small></span></button>
      <button type="button" className="pen-sign-out" disabled title="This local workspace does not have an account session."><LogOut aria-hidden="true" />Sign out</button>
    </PenDialog>
  </>;
}
