import { useEffect, useState } from "react";
import { createProject, listProjects, type ProjectRecord } from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FolderOpen, Plus } from "lucide-react";
import { PenDialog } from "./PenDialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** Selects the active project for the whole cockpit and creates new ones
 *  inline (no window.prompt/alert — stays inside the design system).
 *  Lifts selection to App so RunForm and ProfileStudio stay project-scoped. */
export function ProjectSwitcher({
  projectId,
  onSelect,
  compact = false,
  onProjectsChanged,
}: {
  projectId: string | null;
  onSelect: (id: string) => void;
  compact?: boolean;
  onProjectsChanged?: (projects: ProjectRecord[]) => void;
}) {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [managing, setManaging] = useState(false);

  useEffect(() => {
    listProjects().then((ps) => {
      setProjects(ps);
      onProjectsChanged?.(ps);
      if (ps.length && !projectId) onSelect(ps[0].id);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function confirmCreate() {
    const name = newName.trim();
    if (!name) return;
    try {
      const p = await createProject(name);
      setProjects((cur) => [...cur, p]);
      onProjectsChanged?.([...projects, p]);
      onSelect(p.id);
      setCreating(false);
      setNewName("");
      setError(null);
    } catch (err) {
      // Most commonly a 409 duplicate name — shown inline under the input.
      setError(err instanceof Error ? err.message : "could not create project");
    }
  }

  const createForm = (
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void confirmCreate();
        }}
      >
        <Label htmlFor="new-project" className="text-xs text-muted-foreground">
          New project name
        </Label>
        <Input
          id="new-project"
          className="w-44"
          value={newName}
          autoFocus
          onChange={(e) => setNewName(e.target.value)}
        />
        <Button size="sm" type="submit">Create</Button>
        <Button size="sm" variant="ghost" type="button"
          onClick={() => { setCreating(false); setError(null); }}>
          Cancel
        </Button>
        {error && <span className="text-xs text-destructive">{error}</span>}
      </form>
  );
  if (creating && !compact) return createForm;

  return (
    <div className={compact ? "pen-project-picker" : "flex items-center gap-2"}>
      {!compact && <Label htmlFor="project" className="text-xs text-muted-foreground">Project</Label>}
      <Select open={menuOpen} onOpenChange={setMenuOpen} items={projects.map((project) => ({ value: project.id, label: project.name }))} value={projectId ?? null} onValueChange={(v) => v && onSelect(String(v))}>
        <SelectTrigger id="project" aria-label="Project" className={compact ? "pen-project-trigger" : "w-44"}>
          {compact && <span className="pen-project-dot" aria-hidden="true" />}
          <SelectValue placeholder="No projects" />
        </SelectTrigger>
        <SelectContent className={compact ? "pen-project-dropdown" : undefined} align="end" alignItemWithTrigger={!compact} sideOffset={8}>
          {compact && <div className="pen-project-heading"><p>Switch project</p><small>Choose the active workspace</small></div>}
          {projects.map((p, index) => (
            <SelectItem key={p.id} value={p.id} className={compact ? "pen-project-option" : undefined}>
              {compact && <span className={`pen-project-dot pen-dot-${index % 3}`} aria-hidden="true" />}
              <span>{p.name}{compact && <small>{p.id === projectId ? "Current project" : "Workspace"}</small>}</span>
            </SelectItem>
          ))}
          {compact && <div className="pen-project-actions">
            <button type="button" onClick={() => { setMenuOpen(false); setCreating(true); }}><Plus aria-hidden="true" />New project</button>
            <button type="button" onClick={() => { setMenuOpen(false); setManaging(true); }}><FolderOpen aria-hidden="true" />Manage projects</button>
          </div>}
        </SelectContent>
      </Select>
      {!compact && <Button size="sm" variant="secondary" onClick={() => setCreating(true)}>
        New project
      </Button>}
      {compact && <PenDialog open={creating} onOpenChange={setCreating} title="New project" description="Create a workspace for your productions.">{createForm}</PenDialog>}
      {compact && <PenDialog open={managing} onOpenChange={setManaging} title="Manage projects" description="Choose an existing project or create a new workspace."><div className="pen-managed-projects">{projects.map((project) => <button type="button" key={project.id} onClick={() => { onSelect(project.id); setManaging(false); }}><span className="pen-project-dot" />{project.name}<small>{project.id === projectId ? "Current project" : "Switch project"}</small></button>)}<Button onClick={() => { setManaging(false); setCreating(true); }}>New project</Button></div></PenDialog>}
    </div>
  );
}
