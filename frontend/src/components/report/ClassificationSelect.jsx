import { Building2, Globe, Lock } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useToast,
} from "@/components/ui";
import { useSetClassification } from "@/hooks/queries";
import { errorMessage } from "@/lib/apiClient";
import { CLASSIFICATIONS, classificationToken } from "@/lib/format";

/**
 * Classification is shown by an icon, never by a colour.
 *
 * Red in this UI means critical severity. Spending it on a handling caveat
 * two inches from a severity badge would dilute both — so the level carries a
 * glyph instead, and the ladder still reads at a glance.
 */
const ICONS = { globe: Globe, building: Building2, lock: Lock };

export function ClassificationIcon({ level, className = "size-3.5" }) {
  const Icon = ICONS[classificationToken(level).icon] ?? Building2;
  return <Icon className={className} aria-hidden="true" />;
}

export function ClassificationSelect({ reportId, value }) {
  const { toast } = useToast();
  const mutation = useSetClassification();

  async function handleChange(next) {
    if (next === value) return;
    try {
      await mutation.mutateAsync({ reportId, classification: next });
      toast({
        variant: "success",
        title: `Reclassified as ${next}`,
        description: classificationToken(next).description,
      });
    } catch (error) {
      toast({
        variant: "error",
        title: "Could not reclassify",
        description: errorMessage(error),
      });
    }
  }

  return (
    <Select value={value} onValueChange={handleChange} disabled={mutation.isPending}>
      <SelectTrigger
        aria-label="Classification"
        className="h-7 w-auto gap-2 rounded-full border-line-strong px-3 text-xs"
      >
        <ClassificationIcon level={value} />
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {CLASSIFICATIONS.map((level) => (
          <SelectItem key={level} value={level}>
            <span className="flex items-center gap-2">
              <ClassificationIcon level={level} />
              {level}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
