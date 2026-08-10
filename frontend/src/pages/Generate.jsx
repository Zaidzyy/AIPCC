import { AlertTriangle, ArrowRight, FileUp, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { AmbientVideo } from "@/components/common/AmbientVideo";
import { PageHeader } from "@/components/common/PageHeader";
import { GenerationProgress } from "@/components/report/GenerationProgress";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  Field,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  useToast,
} from "@/components/ui";
import {
  useDocuments,
  useInvalidateAfterGeneration,
  useUploadDocument,
} from "@/hooks/queries";
import { useGenerationStream } from "@/hooks/useGenerationStream";
import { errorMessage } from "@/lib/apiClient";
import { CLASSIFICATIONS, formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

const ACCEPTED = [".csv", ".json", ".txt", ".log"];

export function Generate() {
  const navigate = useNavigate();
  const { toast } = useToast();

  const documents = useDocuments();
  const [progress, setProgress] = useState(null);
  const upload = useUploadDocument({ onProgress: setProgress });
  const generation = useGenerationStream();
  const invalidate = useInvalidateAfterGeneration();

  const [documentId, setDocumentId] = useState("");
  const [reportName, setReportName] = useState("");
  const [classification, setClassification] = useState("Internal");

  const selected = documents.data?.find((d) => d.document_id === documentId);

  async function handleUpload(file) {
    if (!file) return;
    setProgress(0);
    try {
      const created = await upload.mutateAsync(file);
      setDocumentId(created.document_id);
      if (!reportName) setReportName(`${created.document_name} analysis`);
      toast({
        variant: "success",
        title: "File ingested",
        description: `${created.document_name} — ${created.chunk_count} chunks embedded.`,
      });
    } catch (error) {
      toast({
        variant: "error",
        title: "Upload failed",
        description: errorMessage(error),
      });
    } finally {
      setProgress(null);
    }
  }

  function handleGenerate(event) {
    event.preventDefault();
    // Deliberately not awaited: the stream resolves only when generation ends,
    // and the UI has to render its first frame long before that.
    generation.start({ documentId, reportName: reportName.trim(), classification });
  }

  // Navigation happens on the terminal event rather than inside the handler,
  // so a run that was resumed after a remount lands in the same place as one
  // watched from the start.
  useEffect(() => {
    const result = generation.result;
    if (generation.phase !== "done" || !result) return;
    // A failed report is still a stored row, so the list and the aggregates
    // have changed either way.
    invalidate();
    if (result.status === "failed") return; // shown below, with its errors
    navigate(`/reports/${result.report_id}`);
  }, [generation.phase, generation.result, invalidate, navigate]);

  // Generation replaces the form entirely, so the loading clip is never on
  // screen at the same time as the object-core loop — manifest rule 1.
  if (generation.phase === "streaming" || generation.phase === "reconnecting") {
    return (
      <GenerationProgress
        name={generation.reportName}
        sections={generation.sections}
        reconnecting={generation.phase === "reconnecting"}
      />
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="Analysis"
        title="Generate a report"
        description="Upload a security log, then produce a structured report: attack types, risk assessment, vulnerabilities, anomalies and an event timeline."
      />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="relative overflow-hidden">
          {/* The showpiece clip, used in exactly one place in the app. */}
          <AmbientVideo clip="object-core" opacity="opacity-25" scrim="bg-surface/85" />
          <CardHeader className="relative">
            <CardTitle>1 — Provide a log</CardTitle>
          </CardHeader>
          <CardBody className="relative">
            <Dropzone
              onFile={handleUpload}
              uploading={upload.isPending}
              progress={progress}
            />

            <div className="mt-5">
              <p className="eyebrow mb-2">Or choose an ingested document</p>
              {documents.isPending ? (
                <Skeleton className="h-9.5 w-full" />
              ) : documents.data.length === 0 ? (
                <p className="text-sm text-ink-faint">
                  Nothing ingested yet. Upload a file to get started.
                </p>
              ) : (
                <Select value={documentId} onValueChange={setDocumentId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a document" />
                  </SelectTrigger>
                  <SelectContent>
                    {documents.data.map((document) => (
                      <SelectItem key={document.document_id} value={document.document_id}>
                        {document.document_name} · {formatBytes(document.document_size)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>2 — Describe the report</CardTitle>
          </CardHeader>
          <CardBody>
            <form onSubmit={handleGenerate} className="space-y-4">
              <Field
                label="Report name"
                required
                hint={selected ? `Source: ${selected.document_name}` : undefined}
              >
                {(props) => (
                  <Input
                    {...props}
                    value={reportName}
                    onChange={(event) => setReportName(event.target.value)}
                    placeholder="Q3 perimeter log review"
                    maxLength={255}
                    required
                  />
                )}
              </Field>

              <div className="space-y-1.5">
                <p className="eyebrow">Classification</p>
                <Select value={classification} onValueChange={setClassification}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CLASSIFICATIONS.map((value) => (
                      <SelectItem key={value} value={value}>
                        {value}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Button
                type="submit"
                variant="primary"
                className="w-full"
                disabled={!documentId || !reportName.trim()}
              >
                Generate report
                <ArrowRight />
              </Button>

              {generation.phase === "error" && (
                <GenerationFailure message={errorMessage(generation.error)} />
              )}
              {generation.phase === "done" && generation.result?.status === "failed" && (
                <GenerationFailure
                  message="Report generation produced no usable sections."
                  sections={generation.result.errors}
                  reportId={generation.result.report_id}
                />
              )}
            </form>
          </CardBody>
        </Card>
      </div>
    </>
  );
}

function Dropzone({ onFile, uploading, progress }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        onFile(event.dataTransfer.files?.[0]);
      }}
      className={cn(
        "rounded-md border border-dashed px-5 py-8 text-center transition-colors",
        dragging ? "border-ink bg-raised" : "border-line-strong bg-void/40",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED.join(",")}
        className="sr-only"
        onChange={(event) => {
          onFile(event.target.files?.[0]);
          event.target.value = "";
        }}
      />

      {uploading ? (
        <div className="space-y-2.5">
          <p className="eyebrow">
            {/* Ingestion is synchronous on the backend: the upload bar finishing
                is not the end of the work, so say what is actually happening. */}
            {progress === 100 ? "Embedding into the vector store" : "Uploading"}
          </p>
          <div className="h-1 overflow-hidden rounded-full bg-line">
            <div
              className={cn(
                "h-full rounded-full bg-ink transition-[width] duration-300",
                progress === 100 && "animate-shimmer",
              )}
              style={{ width: `${progress ?? 0}%` }}
            />
          </div>
        </div>
      ) : (
        <>
          <FileUp className="mx-auto mb-3 size-5 text-ink-faint" aria-hidden="true" />
          <p className="text-sm text-ink-dim">Drop a log file here</p>
          <p className="mt-1 text-xs text-ink-faint">
            {ACCEPTED.join(" · ")} — up to 50 MB
          </p>
          <Button
            type="button"
            size="sm"
            className="mt-4"
            onClick={() => inputRef.current?.click()}
          >
            <Upload />
            Choose a file
          </Button>
        </>
      )}
    </div>
  );
}

/**
 * A generation that produced nothing usable.
 *
 * The stream's terminal frame carries the same typed `SectionError` list the
 * non-streaming 502 does, and flattening it into "Something went wrong" would
 * throw away the only thing that makes the failure actionable.
 */
function GenerationFailure({ message, sections = [], reportId = null }) {
  return (
    <div className="rounded-md border border-critical/30 bg-critical/8 p-4">
      <div className="flex items-start gap-2.5">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-critical" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[0.8125rem] font-medium text-critical">{message}</p>

          {sections.length > 0 && (
            <ul className="mt-2.5 space-y-1.5">
              {sections.map((section, index) => (
                <li key={index} className="text-[0.8125rem] text-ink-dim">
                  <span className="ident text-ink">{section.section}</span>{" "}
                  <span className="text-ink-faint">({section.stage})</span> — {section.detail}
                </li>
              ))}
            </ul>
          )}

          <p className="mt-3 text-xs text-ink-faint">
            If every section failed at the <span className="ident">llm</span> stage, the
            configured provider is unreachable — check <span className="ident">LLM_PROVIDER</span>{" "}
            and its API key in the backend environment.
          </p>

          {reportId && (
            <Button variant="ghost" size="sm" className="mt-2 -ml-3" asChild>
              <Link to={`/reports/${reportId}`}>
                View the stored attempt
                <ArrowRight />
              </Link>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
