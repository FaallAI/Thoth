import type { ArtifactRef } from "@/api/control-plane";

/** A blob URL drops the server's Content-Disposition, so the saved name carries the extension. */
export function downloadName(artifact: ArtifactRef): string {
  return `${artifact.artifact_id}${artifact.location.match(/\.[A-Za-z0-9]+$/)?.[0] ?? ""}`;
}
