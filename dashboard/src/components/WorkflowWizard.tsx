import { useEffect, useRef, useState } from "react";

import { PlanLimitError, type ControlPlaneClient, type StylePreset, type WorkflowRequest } from "@/api/control-plane";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ArrowRight, ArrowUpRight, Link2 } from "lucide-react";

type WizardClient = Pick<ControlPlaneClient, "listStylePresets"> & {
  createWorkflow: (request: WorkflowRequest, idempotencyKey: string) => Promise<{ workflow_id: string }>;
};

const LIMIT_MESSAGE = "This month's allowance is used up. Open Billing to choose a plan.";

export function WorkflowWizard({
  client,
  onStarted,
  disabledReason,
}: {
  client: WizardClient;
  onStarted: (workflowId: string) => void;
  disabledReason?: string;
}) {
  const [url, setUrl] = useState("");
  const [styles, setStyles] = useState<StylePreset[]>([]);
  const [style, setStyle] = useState("");
  const [review, setReview] = useState(true);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // A failed start may still have started the workflow (a 503 can come after the start), so a
  // retry of the same request reuses its key; the server then returns that workflow, not a twin.
  const attempt = useRef<{ body: string; key: string } | null>(null);

  useEffect(() => {
    let live = true;
    void client.listStylePresets().then(
      (presets) => {
        if (!live) return;
        setStyles(presets);
        setStyle((current) => current || presets[0]?.preset_id || "");
      },
      () => live && setError("Could not load video styles."),
    );
    return () => { live = false; };
  }, [client]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabledReason) return;
    setError("");
    setSubmitting(true);
    const request: WorkflowRequest = {
      source: { url, intent: "produce_video" },
      style: { preset_id: style },
      output: { format: "mp4", language: "id" },
      review: { require_publish_approval: review },
    };
    const body = JSON.stringify(request);
    const key = attempt.current?.body === body ? attempt.current.key : crypto.randomUUID();
    attempt.current = { body, key };
    try {
      const { workflow_id } = await client.createWorkflow(request, key);
      attempt.current = null;
      onStarted(workflow_id);
    } catch (failure) {
      setError(
        failure instanceof PlanLimitError
          ? LIMIT_MESSAGE
          : "Could not start the workflow. Check the source and try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card className="workflow-create">
      <CardHeader><div><p className="dashboard-eyebrow">Start a new run</p><CardTitle>From source to content set</CardTitle></div><ArrowUpRight aria-hidden="true" /></CardHeader>
      <CardContent>
        <form className="flex flex-col gap-4" onSubmit={submit}>
          <div className="grid gap-2">
            <Label htmlFor="workflow-source">Source URL</Label>
            <div className="pen-source-input"><Link2 aria-hidden="true" /><Input id="workflow-source" placeholder="Paste a TikTok, YouTube, or source URL" value={url} onChange={(event) => setUrl(event.target.value)} required type="url" /></div>
          </div>
          <div className="pen-launch-controls"><div className="grid gap-2">
            <Label htmlFor="workflow-style">Style profile</Label>
            <select id="workflow-style" aria-label="Style" value={style} onChange={(event) => setStyle(event.target.value)} required>
              {styles.map((preset) => <option key={preset.preset_id} value={preset.preset_id}>{preset.label}</option>)}
            </select>
          </div>
          <div className="grid gap-2"><Label htmlFor="workflow-review">Review mode</Label>
            <select id="workflow-review" value={review ? "publish" : "none"} onChange={(event) => setReview(event.target.value === "publish")}>
              <option value="publish">Approval before the content set is final</option><option value="none">No publish approval</option>
            </select>
          </div></div>
          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
          {error === LIMIT_MESSAGE && <a className="text-sm underline" href="/billing">Open Billing</a>}
          <div className="pen-launch-footer"><span title={disabledReason || "Duration depends on the source and configured providers."}>{disabledReason || "Estimated run time varies"}</span><Button disabled={submitting || !style || Boolean(disabledReason)} type="submit">Start pipeline<ArrowRight aria-hidden="true" /></Button></div>
        </form>
      </CardContent>
    </Card>
  );
}
