"use client";

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  Database,
  Play,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import {
  Card,
  ErrorState,
  PageHeader,
  Pill,
  Skeleton,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { IngestionRun, ScoringProfile, SourceStatus } from "@/lib/types";
import { COMPONENT_LABEL, formatDateTime, relativeDays, titleCase } from "@/lib/format";

const STATUS_ICON: Record<string, typeof CheckCircle2> = {
  idle: CircleSlash,
  running: RefreshCw,
  success: CheckCircle2,
  failed: XCircle,
};

/** The API writes ok/error/never_run; the UI icons use success/failed/idle. */
function normaliseStatus(status: string): string {
  return { ok: "success", error: "failed", never_run: "idle" }[status] ?? status;
}

function statusTone(status: string): "good" | "danger" | "amber" | "muted" {
  if (status === "success") return "good";
  if (status === "failed") return "danger";
  if (status === "running") return "amber";
  return "muted";
}

export default function SourcesPage() {
  const { isAdmin, canWrite } = useAuth();
  const { data, error, loading, reload } = useApi<{ data: SourceStatus[] }>("/sync/status");
  const profiles = useApi<{ data: ScoringProfile[] }>("/scoring-profiles");
  const [selectedSource, setSelectedSource] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ message: string; tone: "ok" | "error" } | null>(null);

  const sources = data?.data ?? [];
  const mockSource = sources.find((source) => source.provider_key === "mock");
  const activeId = selectedSource || mockSource?.id || "";
  const runs = useApi<{ data: IngestionRun[]; meta: { page: number; per_page: number } }>(
    activeId ? `/data-sources/${activeId}/runs?per_page=10` : null,
  );

  async function sync(source: SourceStatus) {
    setBusyId(source.id);
    setNotice(null);
    try {
      const response = await api.post<{ job: { status: string }; run: IngestionRun }>(
        `/data-sources/${source.id}/sync`,
      );
      const run = response.run;
      setNotice({
        message: `Sync ${response.job.status}: ${run.records_fetched} fetched, ${run.records_written} written, ${run.records_rejected} rejected.`,
        tone: run.status === "success" ? "ok" : "error",
      });
      reload();
      runs.reload();
    } catch (err) {
      setNotice({ message: (err as Error).message, tone: "error" });
    } finally {
      setBusyId(null);
    }
  }

  async function toggle(source: SourceStatus) {
    try {
      await api.patch(`/data-sources/${source.id}`, { enabled: !source.enabled });
      reload();
    } catch (err) {
      setNotice({ message: (err as Error).message, tone: "error" });
    }
  }

  const activeProfile = (profiles.data?.data ?? []).find((profile) => profile.is_active);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Ingestion"
        title="Data sources"
        description="Phase 1 runs a deterministic synthetic provider and a CSV importer. Other providers are registered but disabled — nothing scrapes or bypasses access controls."
        actions={
          <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
            Refresh
          </button>
        }
      />

      {notice ? (
        <p
          role="status"
          className="rounded-md border px-3 py-2 text-sm"
          style={{
            borderColor: notice.tone === "error" ? "var(--color-danger)" : "var(--color-good)",
            color: notice.tone === "error" ? "var(--color-danger)" : "var(--color-good)",
          }}
        >
          {notice.message}
        </p>
      ) : null}

      {error ? <ErrorState message={error} onRetry={reload} /> : null}

      {loading && !data ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-40" />
          ))}
        </div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {sources.map((source) => {
            const syncStatus = normaliseStatus(source.sync_status);
            const Icon = STATUS_ICON[syncStatus] ?? CircleSlash;
            const isMock = source.provider_key === "mock";
            return (
              <Card key={source.id} className="flex flex-col p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-sm font-semibold tracking-tight">{source.provider_name}</h2>
                      <Pill tone={source.enabled ? "good" : "muted"}>
                        {source.enabled ? "enabled" : "disabled"}
                      </Pill>
                      {source.is_synthetic ? <Pill tone="amber">synthetic</Pill> : null}
                      {!source.configured ? <Pill tone="danger">not configured</Pill> : null}
                    </div>
                    <p className="num mt-1 text-[0.68rem] text-muted">
                      {source.provider_key} · {source.source_type}
                    </p>
                  </div>
                  <span className="flex items-center gap-1.5 text-xs text-muted">
                    <Icon
                      className={`h-4 w-4 ${syncStatus === "running" ? "animate-spin" : ""}`}
                      aria-hidden="true"
                    />
                    {titleCase(syncStatus)}
                  </span>
                </div>

                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                  <div>
                    <dt className="text-muted">Last sync</dt>
                    <dd>{relativeDays(source.last_sync_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Rate limit</dt>
                    <dd className="num">{source.rate_limit_per_min}/min</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Credentials</dt>
                    <dd>{source.secret_ref.length ? source.secret_ref.join(", ") : "none required"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Failures</dt>
                    <dd className="num">{source.consecutive_failures}</dd>
                  </div>
                </dl>

                {source.last_error ? (
                  <p className="mt-2 flex items-start gap-1.5 text-[0.7rem]" style={{ color: "var(--color-danger)" }}>
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    {source.last_error}
                  </p>
                ) : null}

                <div className="mt-3 flex items-center justify-between gap-2 border-t border-line pt-3">
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setSelectedSource(source.id)}
                  >
                    <Database className="h-3.5 w-3.5" aria-hidden="true" /> Activity
                  </button>
                  <div className="flex items-center gap-1.5">
                    {isAdmin ? (
                      <button type="button" className="btn btn-sm" onClick={() => toggle(source)}>
                        {source.enabled ? "Disable" : "Enable"}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      onClick={() => sync(source)}
                      disabled={!canWrite || !source.enabled || !isMock || busyId === source.id}
                      title={
                        !isMock
                          ? "Only the mock provider is enabled in Phase 1"
                          : !source.enabled
                            ? "Enable the source first"
                            : "Run a mock sync"
                      }
                    >
                      <Play className="h-3.5 w-3.5" aria-hidden="true" />
                      {busyId === source.id ? "Syncing…" : "Run sync"}
                    </button>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold tracking-tight">Ingestion runs</h2>
            <p className="mt-0.5 text-xs text-muted">
              Phase 1 syncs are synchronous; the job record is written as the run finishes.
            </p>
          </div>
          <select
            className="field w-auto text-xs"
            value={activeId}
            onChange={(event) => setSelectedSource(event.target.value)}
            aria-label="Choose source activity"
          >
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.provider_name}
              </option>
            ))}
          </select>
        </div>

        {runs.loading && !runs.data ? (
          <Skeleton className="mt-4 h-32" />
        ) : runs.data?.data.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Job</th>
                  <th>Status</th>
                  <th className="text-right">Fetched</th>
                  <th className="text-right">Written</th>
                  <th className="text-right">Rejected</th>
                  <th className="text-right">Finished</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.data.map((run) => (
                  <tr key={run.id}>
                    <td className="whitespace-nowrap text-xs">{formatDateTime(run.started_at)}</td>
                    <td className="num text-xs">{run.job_name}</td>
                    <td>
                      <Pill tone={statusTone(run.status)}>{titleCase(run.status)}</Pill>
                    </td>
                    <td className="num text-right text-xs">{run.records_fetched}</td>
                    <td className="num text-right text-xs">{run.records_written}</td>
                    <td className="num text-right text-xs">{run.records_rejected}</td>
                    <td className="whitespace-nowrap text-right text-xs text-muted">
                      {formatDateTime(run.finished_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-4 text-sm text-muted">
            {runs.error ?? "No runs recorded for this source yet."}
          </p>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold tracking-tight">Scoring profile</h2>
              <p className="mt-0.5 text-xs text-muted">
                Weights apply to available components; unavailable weights are renormalised.
              </p>
            </div>
            {activeProfile ? <Pill tone="accent">v{activeProfile.version}</Pill> : null}
          </div>
          {profiles.loading && !profiles.data ? (
            <Skeleton className="mt-3 h-40" />
          ) : activeProfile ? (
            <>
              <p className="mt-3 text-xs">
                <span className="font-medium">{activeProfile.name}</span> · {activeProfile.country}
              </p>
              <dl className="mt-2 space-y-1.5">
                {Object.entries(activeProfile.weights).map(([key, weight]) => (
                  <div key={key} className="flex items-center justify-between gap-3 text-xs">
                    <dt>{COMPONENT_LABEL[key] ?? titleCase(key)}</dt>
                    <dd className="num">{(weight * 100).toFixed(0)}%</dd>
                  </div>
                ))}
              </dl>
              <div className="mt-3 border-t border-line pt-3">
                <p className="eyebrow mb-1.5">Thresholds</p>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(activeProfile.thresholds).map(([key, value]) => (
                    <Pill key={key}>
                      {titleCase(key)} ≥ {value}
                    </Pill>
                  ))}
                </div>
              </div>
            </>
          ) : (
            <p className="mt-3 text-sm text-muted">No active scoring profile.</p>
          )}
        </Card>

        <Card className="p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold tracking-tight">
            <ShieldCheck className="h-4 w-4 text-accent" aria-hidden="true" /> Source policy
          </h2>
          <ul className="mt-2 space-y-2 text-xs leading-relaxed text-muted">
            <li>
              Only the mock provider and CSV importer are active in Phase 1. They require no
              credentials and no external requests.
            </li>
            <li>
              Google Trends, eBay AU, Exploding Topics, Amazon AU, TikTok and CJ Dropshipping are
              registered with their status. Unavailable providers stay disabled rather than being
              approximated silently.
            </li>
            <li>
              No scraping, CAPTCHA bypass or anti-bot circumvention. Phase 2 providers activate only
              with authorised credentials and terms-compliant access.
            </li>
            <li>
              Synthetic records carry <span className="num">is_synthetic</span> through observations,
              products, suppliers and API payloads.
            </li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
