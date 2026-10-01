import { useState } from "react";
import { ArrowRight, CirclePlus, FileText, Info, Layers, LayoutTemplate, Link2, Video } from "lucide-react";
import { PenDialog } from "./PenDialog";

export type LocalWorkflowDraft = { name: string; startingPoint: "guided" | "blank"; firstStep: string | null };
const stages = [
  { name: "Source", hint: "Bring in a URL or media", icon: Link2 },
  { name: "Script", hint: "Start from a written idea", icon: FileText },
  { name: "Media", hint: "Create visual or audio assets", icon: Layers },
  { name: "Render", hint: "Assemble an existing cut", icon: Video },
];

export function WorkflowDraftDialog({ open, onOpenChange, projectName, onCreate }: {
  open: boolean; onOpenChange: (open: boolean) => void; projectName: string;
  onCreate: (draft: LocalWorkflowDraft) => void;
}) {
  const [name, setName] = useState("");
  const [startingPoint, setStartingPoint] = useState<"guided" | "blank">("guided");
  const [configured, setConfigured] = useState(false);
  const [chooseStep, setChooseStep] = useState(false);
  const [firstStep, setFirstStep] = useState<string | null>(null);
  return <PenDialog open={open} onOpenChange={onOpenChange} title="Create a workflow" description="Set up a reusable pipeline for your next production." eyebrow="New workflow" className={`pen-workflow-dialog ${chooseStep ? 'pen-workflow-choose' : ''}`}>
    <form onSubmit={(event) => { event.preventDefault(); if (!name.trim()) return; onCreate({ name: name.trim(), startingPoint, firstStep: startingPoint === "blank" ? firstStep : null }); onOpenChange(false); }}>
      <div className="pen-draft-fields">
        <div className="pen-draft-project"><span>Project</span><i className="pen-project-dot" />{projectName || "Select a project"}</div>
        <label className="pen-draft-name">Workflow name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="Name this workflow" required /></label>
        <fieldset><legend>Starting point</legend><div className="pen-starting-options">
          <button type="button" aria-pressed={startingPoint === "guided"} onClick={() => { setStartingPoint("guided"); setConfigured(true); setChooseStep(false); }}><LayoutTemplate aria-hidden="true" /><strong>Guided pipeline</strong><small>Source → Script → Media → Render</small></button>
          <button type="button" aria-pressed={startingPoint === "blank"} onClick={() => { setStartingPoint("blank"); setConfigured(true); setChooseStep(false); }}><CirclePlus aria-hidden="true" /><strong>Blank workflow</strong><small>Build each step yourself</small></button>
        </div></fieldset>
        {configured && startingPoint === "guided" && <section className="pen-draft-preview"><h3>Included stages</h3><div className="pen-guided-stage-strip">{stages.map(({ name: label }, index) => <div key={label}><span>{String(index + 1).padStart(2, '0')}</span><strong>{label}</strong><small>{['Ingest media', 'Shape story', 'Generate assets', 'Deliver cut'][index]}</small></div>)}</div></section>}
        {startingPoint === "blank" && <section className="pen-draft-preview"><h3>{chooseStep ? "Choose first step" : "Empty canvas preview"}</h3>{chooseStep ? <div className="pen-first-step-list">{stages.map(({ name: label, hint }, index) => <button type="button" key={label} aria-pressed={firstStep === label} onClick={() => setFirstStep(label)}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{label}</strong><small>{hint}</small></div></button>)}</div> : <button type="button" className="pen-add-first-step" onClick={() => setChooseStep(true)}><CirclePlus aria-hidden="true" /><div><strong>Add your first step</strong><small>Start with a trigger, then connect actions in the editor.</small></div></button>}</section>}
        <p className="pen-draft-note"><Info aria-hidden="true" /><span>{startingPoint === "blank" ? "This session keeps the draft locally. Custom stage execution is unavailable." : "Create a local draft for this session. Add a source below when you run it."}</span></p>
      </div>
      <footer className="pen-dialog-actions"><button type="button" onClick={() => onOpenChange(false)}>Cancel</button><button type="submit" disabled={!name.trim() || !startingPoint || (chooseStep && !firstStep)} title="Creates a local draft for this session; it does not start or publish a run.">Create draft<ArrowRight aria-hidden="true" /></button></footer>
    </form>
  </PenDialog>;
}
