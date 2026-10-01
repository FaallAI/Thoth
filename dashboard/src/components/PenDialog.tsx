import { Dialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

/** Shared accessible dialog chrome measured from the selected dashboard design. */
export function PenDialog({ open, onOpenChange, title, description, eyebrow, className = "", children }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  eyebrow?: string;
  className?: string;
  children: ReactNode;
}) {
  return <Dialog.Root open={open} onOpenChange={onOpenChange}>
    <Dialog.Portal>
      <Dialog.Backdrop className="pen-dialog-backdrop" />
      <Dialog.Popup className={`pen-dialog ${className}`}>
        <header className="pen-dialog-heading">
          <div>{eyebrow && <p className="dashboard-eyebrow">{eyebrow}</p>}
            <Dialog.Title>{title}</Dialog.Title>
            {description && <Dialog.Description>{description}</Dialog.Description>}
          </div>
          <Dialog.Close className="pen-dialog-close" aria-label={`Close ${title}`}><X aria-hidden="true" /></Dialog.Close>
        </header>
        {children}
      </Dialog.Popup>
    </Dialog.Portal>
  </Dialog.Root>;
}
