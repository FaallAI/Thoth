/** A labelled on/off switch, shared by the Story inspector and the timeline transport. */
export function Switch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (on: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex items-center justify-between rounded-md px-1 py-1 text-sm text-ink focus-visible:outline-2 focus-visible:outline-copper"
    >
      {label}
      <span aria-hidden="true" className={`flex h-5 w-9 items-center rounded-full p-0.5 ${checked ? "bg-copper" : "bg-well"}`}>
        <span className={`size-4 rounded-full bg-ink transition-transform ${checked ? "translate-x-4" : ""}`} />
      </span>
    </button>
  );
}
