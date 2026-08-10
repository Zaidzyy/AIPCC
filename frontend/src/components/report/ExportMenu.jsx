import { Download, FileText, Loader2 } from "lucide-react";
import { useState } from "react";

import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
  useToast,
} from "@/components/ui";
import { saveBlob } from "@/lib/download";

const FORMATS = [
  { value: "pdf", label: "PDF", hint: "For reading and printing" },
  { value: "docx", label: "Word (DOCX)", hint: "For editing into a longer write-up" },
];

/**
 * Export a report to a file.
 *
 * `download` is injected rather than assumed, because the same menu serves the
 * authenticated Report Detail page and the public share view — which hit
 * different endpoints and, deliberately, produce documents with different
 * contents.
 *
 * The error path is generic on purpose: the endpoint answers with a blob, so a
 * failure arrives as JSON inside a Blob that `errorMessage` cannot read. Rather
 * than parse it back out for a case that means "the report went away", the
 * toast says what the user can act on.
 */
export function ExportMenu({ download, disabled = false }) {
  const { toast } = useToast();
  const [pending, setPending] = useState(null);

  async function handle(format) {
    setPending(format);
    try {
      const { blob, filename } = await download(format);
      saveBlob(blob, filename);
      toast({ variant: "success", title: `Exported ${filename}` });
    } catch {
      toast({
        variant: "error",
        title: "Export failed",
        description: "The report could not be rendered. It may have been deleted.",
      });
    } finally {
      setPending(null);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" disabled={disabled || Boolean(pending)}>
          {pending ? <Loader2 className="animate-spin" /> : <Download />}
          Export
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-60">
        <DropdownMenuLabel>Download as</DropdownMenuLabel>
        {FORMATS.map(({ value, label, hint }) => (
          <DropdownMenuItem key={value} onSelect={() => handle(value)}>
            <FileText />
            <span className="min-w-0">
              <span className="block text-ink">{label}</span>
              <span className="block text-xs text-ink-faint">{hint}</span>
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
