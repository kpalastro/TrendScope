"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Calculator,
  FolderOpen,
  RotateCcw,
  Save,
  Trash2,
} from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import {
  Card,
  EmptyState,
  ErrorState,
  KeyValue,
  Modal,
  PageHeader,
  Pill,
  Skeleton,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type {
  ProfitAssumptions,
  ProfitCalculation,
  ProfitInputs,
  ProfitScenario,
} from "@/lib/types";
import { formatDateTime, money, pct } from "@/lib/format";

type FormValues = {
  currency: string;
  supplier_price: string;
  international_shipping: string;
  import_duty_rate_pct: string;
  supplier_charges_gst: boolean;
  gst_registered: boolean;
  gst_rate_pct: string;
  claim_input_tax_credit: boolean;
  domestic_fulfilment: string;
  packaging: string;
  payment_fee_pct: string;
  payment_fee_fixed: string;
  advertising_cost_per_order: string;
  selling_price_inc_gst: string;
  return_rate_pct: string;
  monthly_order_volumes: string;
};

const FALLBACK_DEFAULTS: FormValues = {
  currency: "AUD",
  supplier_price: "12.40",
  international_shipping: "3.10",
  import_duty_rate_pct: "0",
  supplier_charges_gst: false,
  gst_registered: true,
  gst_rate_pct: "10",
  claim_input_tax_credit: true,
  domestic_fulfilment: "8.50",
  packaging: "1.20",
  payment_fee_pct: "1.75",
  payment_fee_fixed: "0.30",
  advertising_cost_per_order: "12.00",
  selling_price_inc_gst: "69.95",
  return_rate_pct: "3",
  monthly_order_volumes: "100, 500, 1000, 5000",
};

const REQUIRED_NUMBERS: (keyof FormValues)[] = [
  "supplier_price",
  "international_shipping",
  "import_duty_rate_pct",
  "gst_rate_pct",
  "domestic_fulfilment",
  "packaging",
  "payment_fee_pct",
  "payment_fee_fixed",
  "advertising_cost_per_order",
  "selling_price_inc_gst",
  "return_rate_pct",
];

const CURRENCIES = ["AUD", "NZD", "USD", "GBP", "EUR"];

function fromInputs(inputs: Partial<ProfitInputs>): FormValues {
  const value = <K extends keyof ProfitInputs>(key: K) =>
    inputs[key] ?? FALLBACK_DEFAULTS[key as keyof FormValues];
  return {
    currency: String(value("currency") ?? FALLBACK_DEFAULTS.currency),
    supplier_price: String(value("supplier_price")),
    international_shipping: String(value("international_shipping")),
    import_duty_rate_pct: String(value("import_duty_rate_pct")),
    supplier_charges_gst: Boolean(value("supplier_charges_gst")),
    gst_registered: Boolean(value("gst_registered")),
    gst_rate_pct: String(value("gst_rate_pct")),
    claim_input_tax_credit: Boolean(value("claim_input_tax_credit")),
    domestic_fulfilment: String(value("domestic_fulfilment")),
    packaging: String(value("packaging")),
    payment_fee_pct: String(value("payment_fee_pct")),
    payment_fee_fixed: String(value("payment_fee_fixed")),
    advertising_cost_per_order: String(value("advertising_cost_per_order")),
    selling_price_inc_gst: String(value("selling_price_inc_gst")),
    return_rate_pct: String(value("return_rate_pct")),
    monthly_order_volumes: Array.isArray(inputs.monthly_order_volumes)
      ? inputs.monthly_order_volumes.join(", ")
      : FALLBACK_DEFAULTS.monthly_order_volumes,
  };
}

function toPayload(values: FormValues): ProfitInputs {
  return {
    currency: values.currency.toUpperCase().slice(0, 3) || "AUD",
    supplier_price: values.supplier_price.trim(),
    international_shipping: values.international_shipping.trim(),
    import_duty_rate_pct: Number(values.import_duty_rate_pct || 0),
    supplier_charges_gst: values.supplier_charges_gst,
    gst_registered: values.gst_registered,
    gst_rate_pct: Number(values.gst_rate_pct || 0),
    claim_input_tax_credit: values.claim_input_tax_credit,
    domestic_fulfilment: values.domestic_fulfilment.trim(),
    packaging: values.packaging.trim(),
    payment_fee_pct: Number(values.payment_fee_pct || 0),
    payment_fee_fixed: values.payment_fee_fixed.trim(),
    advertising_cost_per_order: values.advertising_cost_per_order.trim(),
    selling_price_inc_gst: values.selling_price_inc_gst.trim(),
    return_rate_pct: Number(values.return_rate_pct || 0),
    monthly_order_volumes: values.monthly_order_volumes
      .split(/[\s,]+/)
      .filter(Boolean)
      .map(Number)
      .filter((item) => Number.isFinite(item) && item >= 0)
      .map((item) => Math.floor(item)),
  };
}

function isComplete(values: FormValues): boolean {
  if (!REQUIRED_NUMBERS.every((key) => String(values[key]).trim() !== "")) return false;
  return toPayload(values).monthly_order_volumes.length > 0;
}

function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-muted">
        {label}
      </label>
      {children}
      {hint ? <p className="mt-1 text-[0.68rem] leading-relaxed text-muted">{hint}</p> : null}
    </div>
  );
}

function Toggle({
  id,
  label,
  hint,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label
      htmlFor={id}
      className="flex cursor-pointer items-start gap-2 rounded-md border border-line bg-bg px-3 py-2.5"
    >
      <input
        id={id}
        type="checkbox"
        className="mt-0.5 h-4 w-4 accent-[var(--color-accent)]"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="min-w-0">
        <span className="block text-xs font-medium">{label}</span>
        <span className="mt-0.5 block text-[0.68rem] leading-relaxed text-muted">{hint}</span>
      </span>
    </label>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="eyebrow border-b border-line pb-1.5">{children}</h3>;
}

export default function ProfitCalculatorPage() {
  const { canWrite } = useAuth();
  const assumptions = useApi<ProfitAssumptions>("/profit/assumptions");
  const scenarios = useApi<{ data: ProfitScenario[] }>("/profit/scenarios");

  const [values, setValues] = useState<FormValues>(FALLBACK_DEFAULTS);
  const [result, setResult] = useState<ProfitCalculation | null>(null);
  const [calcError, setCalcError] = useState<string | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [notice, setNotice] = useState<{ message: string; tone: "ok" | "error" } | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);

  const seeded = useRef(false);
  const touched = useRef(false);
  const requestId = useRef(0);

  // Prefer the server's defaults so the form and the API cannot drift apart.
  useEffect(() => {
    if (seeded.current || !assumptions.data) return;
    seeded.current = true;
    if (!touched.current) setValues(fromInputs(assumptions.data.defaults));
  }, [assumptions.data]);

  // Debounced recalculation. Each response is tagged so a slow earlier request
  // can never overwrite the result for the current inputs.
  useEffect(() => {
    if (!isComplete(values)) {
      requestId.current += 1;
      setResult(null);
      setCalcError(null);
      setCalculating(false);
      return;
    }
    const id = ++requestId.current;
    const handle = window.setTimeout(() => {
      setCalculating(true);
      api
        .post<ProfitCalculation>("/profit/calculate", toPayload(values))
        .then((response) => {
          if (id !== requestId.current) return;
          setResult(response);
          setCalcError(null);
        })
        .catch((err: unknown) => {
          if (id !== requestId.current) return;
          setResult(null);
          setCalcError((err as Error).message);
        })
        .finally(() => {
          if (id === requestId.current) setCalculating(false);
        });
    }, 300);
    return () => window.clearTimeout(handle);
  }, [values]);

  function update<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    touched.current = true;
    setValues((current) => ({ ...current, [key]: value }));
  }

  function reset() {
    touched.current = false;
    setValues(
      fromInputs(assumptions.data ? assumptions.data.defaults : toPayload(FALLBACK_DEFAULTS)),
    );
    setCalcError(null);
    setNotice(null);
  }

  function loadScenario(scenario: ProfitScenario) {
    touched.current = true;
    setValues(fromInputs(scenario.inputs));
    setResult({
      inputs: scenario.inputs,
      outputs: scenario.outputs,
      warnings: scenario.warnings,
      disclaimer: scenario.disclaimer,
      assumptions_version: scenario.assumptions_version,
    });
    setCalcError(null);
    setNotice({ message: `Loaded “${scenario.name}”.`, tone: "ok" });
  }

  async function removeScenario(scenario: ProfitScenario) {
    if (!window.confirm(`Delete the saved scenario “${scenario.name}”?`)) return;
    try {
      await api.delete(`/profit/scenarios/${scenario.id}`);
      setNotice({ message: `Deleted “${scenario.name}”.`, tone: "ok" });
      scenarios.reload();
    } catch (err) {
      setNotice({ message: (err as Error).message, tone: "error" });
    }
  }

  const currency = result?.inputs.currency ?? values.currency.toUpperCase();
  const profit = result ? Number(result.outputs.profit_per_order) : null;
  const scenarioRows = scenarios.data?.data ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Unit economics"
        title="Profit calculator"
        description="Test a real supplier quote with GST, import duty, fulfilment, payment fees, returns and advertising. Outputs are decimal estimates, not forecasts; nothing is stored unless you save a scenario."
        actions={
          <button type="button" className="btn btn-sm" onClick={reset}>
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Reset defaults
          </button>
        }
      />

      {assumptions.error ? (
        <p className="rounded-md border border-line bg-raised px-3 py-2 text-xs text-muted">
          Could not load server defaults; the built-in defaults are shown instead.
        </p>
      ) : null}

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

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <Card className="p-4">
          <form className="space-y-5" onSubmit={(event) => event.preventDefault()}>
            <div className="space-y-3">
              <SectionTitle>Landed cost</SectionTitle>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field id="profit-currency" label="Currency" hint="Supplier and selling currency.">
                  <select
                    id="profit-currency"
                    className="field"
                    value={values.currency}
                    onChange={(event) => update("currency", event.target.value)}
                  >
                    {CURRENCIES.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field id="profit-supplier" label="Supplier price (per unit)">
                  <input
                    id="profit-supplier"
                    type="number"
                    min={0.01}
                    step="0.01"
                    className="field num"
                    value={values.supplier_price}
                    onChange={(event) => update("supplier_price", event.target.value)}
                    required
                  />
                </Field>
                <Field id="profit-shipping" label="International shipping (per unit)">
                  <input
                    id="profit-shipping"
                    type="number"
                    min={0}
                    step="0.01"
                    className="field num"
                    value={values.international_shipping}
                    onChange={(event) => update("international_shipping", event.target.value)}
                    required
                  />
                </Field>
                <Field
                  id="profit-duty"
                  label="Import duty (%)"
                  hint="Confirm the tariff classification; 0% is an assumption."
                >
                  <input
                    id="profit-duty"
                    type="number"
                    min={0}
                    max={100}
                    step="0.1"
                    className="field num"
                    value={values.import_duty_rate_pct}
                    onChange={(event) => update("import_duty_rate_pct", event.target.value)}
                    required
                  />
                </Field>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Toggle
                  id="profit-supplier-gst"
                  label="Supplier charges GST"
                  hint="Their invoice includes GST that may be recoverable."
                  checked={values.supplier_charges_gst}
                  onChange={(value) => update("supplier_charges_gst", value)}
                />
                <Toggle
                  id="profit-gst-registered"
                  label="You are GST-registered"
                  hint="GST is remitted on sales and import GST may be creditable."
                  checked={values.gst_registered}
                  onChange={(value) => update("gst_registered", value)}
                />
                <Toggle
                  id="profit-itc"
                  label="Claim input tax credits"
                  hint="Use the ex-GST landed cost as the cost basis."
                  checked={values.claim_input_tax_credit}
                  onChange={(value) => update("claim_input_tax_credit", value)}
                />
                <Field id="profit-gst-rate" label="GST rate (%)">
                  <input
                    id="profit-gst-rate"
                    type="number"
                    min={0}
                    max={100}
                    step="0.1"
                    className="field num"
                    value={values.gst_rate_pct}
                    onChange={(event) => update("gst_rate_pct", event.target.value)}
                    required
                  />
                </Field>
              </div>
            </div>

            <div className="space-y-3">
              <SectionTitle>Fulfilment and fees</SectionTitle>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field id="profit-fulfilment" label="Domestic fulfilment (per order)">
                  <input
                    id="profit-fulfilment"
                    type="number"
                    min={0}
                    step="0.01"
                    className="field num"
                    value={values.domestic_fulfilment}
                    onChange={(event) => update("domestic_fulfilment", event.target.value)}
                    required
                  />
                </Field>
                <Field id="profit-packaging" label="Packaging (per order)">
                  <input
                    id="profit-packaging"
                    type="number"
                    min={0}
                    step="0.01"
                    className="field num"
                    value={values.packaging}
                    onChange={(event) => update("packaging", event.target.value)}
                    required
                  />
                </Field>
                <Field id="profit-fee-pct" label="Payment fee (%)">
                  <input
                    id="profit-fee-pct"
                    type="number"
                    min={0}
                    max={100}
                    step="0.01"
                    className="field num"
                    value={values.payment_fee_pct}
                    onChange={(event) => update("payment_fee_pct", event.target.value)}
                    required
                  />
                </Field>
                <Field id="profit-fee-fixed" label="Payment fee (fixed per order)">
                  <input
                    id="profit-fee-fixed"
                    type="number"
                    min={0}
                    step="0.01"
                    className="field num"
                    value={values.payment_fee_fixed}
                    onChange={(event) => update("payment_fee_fixed", event.target.value)}
                    required
                  />
                </Field>
              </div>
            </div>

            <div className="space-y-3">
              <SectionTitle>Selling and advertising</SectionTitle>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field
                  id="profit-selling"
                  label="Selling price (inc GST)"
                  hint="The listed price the customer pays."
                >
                  <input
                    id="profit-selling"
                    type="number"
                    min={0.01}
                    step="0.01"
                    className="field num"
                    value={values.selling_price_inc_gst}
                    onChange={(event) => update("selling_price_inc_gst", event.target.value)}
                    required
                  />
                </Field>
                <Field
                  id="profit-ads"
                  label="Advertising (per order)"
                  hint="Reported separately as break-even ad spend."
                >
                  <input
                    id="profit-ads"
                    type="number"
                    min={0}
                    step="0.01"
                    className="field num"
                    value={values.advertising_cost_per_order}
                    onChange={(event) => update("advertising_cost_per_order", event.target.value)}
                    required
                  />
                </Field>
                <Field
                  id="profit-returns"
                  label="Expected returns (%)"
                  hint="Provisioned against the GST-inclusive selling price."
                >
                  <input
                    id="profit-returns"
                    type="number"
                    min={0}
                    max={100}
                    step="0.1"
                    className="field num"
                    value={values.return_rate_pct}
                    onChange={(event) => update("return_rate_pct", event.target.value)}
                    required
                  />
                </Field>
                <Field
                  id="profit-volumes"
                  label="Monthly order volumes"
                  hint="Comma-separated order counts for the scenario table."
                >
                  <input
                    id="profit-volumes"
                    className="field num"
                    value={values.monthly_order_volumes}
                    onChange={(event) => update("monthly_order_volumes", event.target.value)}
                    placeholder="100, 500, 1000"
                    required
                  />
                </Field>
              </div>
            </div>

            {assumptions.data?.notes?.length ? (
              <ul className="list-disc space-y-1 rounded-md border border-line bg-raised py-2.5 pl-7 pr-3 text-[0.7rem] leading-relaxed text-muted">
                {assumptions.data.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}
          </form>
        </Card>

        <div className="space-y-5">
          <Card className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="eyebrow">Profit per order</p>
                <p
                  className="num mt-1 text-3xl font-semibold tracking-tight"
                  style={{ color: profit !== null && profit < 0 ? "var(--color-danger)" : undefined }}
                >
                  {result ? money(result.outputs.profit_per_order, currency) : "—"}
                </p>
                <p className="mt-1 text-xs text-muted">
                  {result
                    ? `${pct(result.outputs.profit_margin_pct)} margin on ${money(
                        result.outputs.selling_price_ex_gst,
                        currency,
                      )} ex-GST revenue`
                    : "Complete the inputs to calculate."}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {calculating ? (
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line border-t-accent" />
                ) : null}
                {result ? (
                  <Pill tone={profit !== null && profit < 0 ? "danger" : "good"}>
                    {profit !== null && profit < 0 ? "Loss-making" : "Profitable"}
                  </Pill>
                ) : null}
              </div>
            </div>

            {calcError ? (
              <div className="mt-4 rounded-md border px-3 py-2.5" style={{ borderColor: "var(--color-danger)" }}>
                <p className="flex items-start gap-2 text-sm" style={{ color: "var(--color-danger)" }}>
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  {calcError}
                </p>
              </div>
            ) : result ? (
              <>
                <div className="mt-4 grid gap-x-6 sm:grid-cols-2">
                  <dl className="border-t border-line">
                    <div className="eyebrow mt-3">Landed cost</div>
                    <KeyValue label="Ex GST">{money(result.outputs.landed_cost_ex_gst, currency)}</KeyValue>
                    <KeyValue label="Cash outflow">{money(result.outputs.landed_cost_cash, currency)}</KeyValue>
                    <KeyValue label="GST on landed cost">
                      {money(result.outputs.gst_on_landed_cost, currency)}
                    </KeyValue>
                    <KeyValue label="Selling price ex GST">
                      {money(result.outputs.selling_price_ex_gst, currency)}
                    </KeyValue>
                    <KeyValue label="GST remitted">{money(result.outputs.gst_remitted_per_sale, currency)}</KeyValue>
                  </dl>
                  <dl className="border-t border-line">
                    <div className="eyebrow mt-3">Per order</div>
                    <KeyValue label="Gross profit">
                      {money(result.outputs.gross_profit, currency)}{" "}
                      <span className="text-xs font-normal text-muted">
                        {pct(result.outputs.gross_margin_pct)}
                      </span>
                    </KeyValue>
                    <KeyValue label="Payment fees">{money(result.outputs.payment_fees, currency)}</KeyValue>
                    <KeyValue label="Returns allowance">
                      {money(result.outputs.returns_allowance, currency)}
                    </KeyValue>
                    <KeyValue label="Contribution">
                      {money(result.outputs.contribution_margin, currency)}{" "}
                      <span className="text-xs font-normal text-muted">
                        {pct(result.outputs.contribution_margin_pct)}
                      </span>
                    </KeyValue>
                    <KeyValue label="Break-even ad cost">
                      {money(result.outputs.break_even_ad_cost, currency)}
                    </KeyValue>
                    <KeyValue label="Advertising">{money(result.outputs.advertising_cost_per_order, currency)}</KeyValue>
                  </dl>
                </div>

                {result.warnings.length ? (
                  <div className="mt-4 rounded-md border border-line bg-raised px-3 py-2.5">
                    <p className="flex items-center gap-1.5 text-xs font-semibold">
                      <AlertTriangle className="h-3.5 w-3.5 text-amber" aria-hidden="true" />
                      Assumptions to confirm
                    </p>
                    <ul className="mt-1 list-disc space-y-1 pl-4 text-[0.7rem] leading-relaxed text-muted">
                      {result.warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <p className="mt-4 text-[0.7rem] leading-relaxed text-muted">{result.disclaimer}</p>
                <p className="mt-1 text-[0.65rem] uppercase tracking-wide text-muted">
                  Assumptions {result.assumptions_version}
                </p>
              </>
            ) : (
              <div className="mt-4 space-y-2">
                <Skeleton className="h-8" />
                <Skeleton className="h-8" />
                <Skeleton className="h-8" />
              </div>
            )}
          </Card>

          {result?.outputs.monthly.length ? (
            <Card className="overflow-hidden">
              <div className="border-b border-line px-4 py-3">
                <h3 className="text-sm font-semibold">At volume</h3>
                <p className="mt-0.5 text-xs text-muted">
                  Monthly totals at the same unit economics; advertising is included.
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th scope="col" className="text-right">Orders</th>
                      <th scope="col" className="text-right">Revenue ex GST</th>
                      <th scope="col" className="text-right">Gross profit</th>
                      <th scope="col" className="text-right">Ad spend</th>
                      <th scope="col" className="text-right">Profit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.outputs.monthly.map((row) => (
                      <tr key={row.orders}>
                        <td className="num text-right">{row.orders.toLocaleString("en-AU")}</td>
                        <td className="num text-right">{money(row.revenue_ex_gst, currency)}</td>
                        <td className="num text-right">{money(row.gross_profit, currency)}</td>
                        <td className="num text-right">{money(row.advertising_spend, currency)}</td>
                        <td
                          className="num text-right font-medium"
                          style={{ color: Number(row.profit) < 0 ? "var(--color-danger)" : undefined }}
                        >
                          {money(row.profit, currency)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ) : null}
        </div>
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold tracking-tight">Saved scenarios</h2>
            <p className="mt-0.5 text-xs text-muted">
              Scenarios store the inputs and the calculation at save time and are private to your account.
            </p>
          </div>
          {canWrite ? (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => setSaveOpen(true)}
              disabled={!isComplete(values)}
            >
              <Save className="h-3.5 w-3.5" aria-hidden="true" /> Save scenario
            </button>
          ) : null}
        </div>

        {scenarios.error ? (
          <div className="p-4">
            <ErrorState message={scenarios.error} onRetry={scenarios.reload} />
          </div>
        ) : scenarios.loading && !scenarios.data ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} className="h-10" />
            ))}
          </div>
        ) : scenarioRows.length === 0 ? (
          <EmptyState
            icon={<FolderOpen className="h-5 w-5" aria-hidden="true" />}
            title="No saved scenarios"
            description="Adjust the calculator to a quote you want to keep, then save it here to reload later."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Scenario</th>
                  <th scope="col" className="text-right">Profit / order</th>
                  <th scope="col" className="text-right">Margin</th>
                  <th scope="col" className="text-right">Updated</th>
                  <th scope="col" className="w-24 text-right">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {scenarioRows.map((scenario) => {
                  const value = Number(scenario.outputs.profit_per_order);
                  return (
                    <tr key={scenario.id}>
                      <td className="max-w-[18rem]">
                        <span className="block truncate text-sm font-medium">{scenario.name}</span>
                        <span className="text-[0.68rem] uppercase tracking-wide text-muted">
                          {scenario.currency} · assumptions {scenario.assumptions_version}
                        </span>
                      </td>
                      <td
                        className="num text-right"
                        style={{ color: value < 0 ? "var(--color-danger)" : undefined }}
                      >
                        {money(scenario.outputs.profit_per_order, scenario.currency)}
                      </td>
                      <td className="num text-right">{pct(scenario.outputs.profit_margin_pct)}</td>
                      <td className="whitespace-nowrap text-right text-xs text-muted">
                        {formatDateTime(scenario.updated_at)}
                      </td>
                      <td className="text-right">
                        <span className="inline-flex gap-1">
                          <button
                            type="button"
                            className="btn btn-sm h-7 w-7 !p-0"
                            onClick={() => loadScenario(scenario)}
                            title="Load into the calculator"
                            aria-label={`Load ${scenario.name}`}
                          >
                            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                          {canWrite ? (
                            <button
                              type="button"
                              className="btn btn-sm h-7 w-7 !p-0"
                              onClick={() => removeScenario(scenario)}
                              title="Delete scenario"
                              aria-label={`Delete ${scenario.name}`}
                              style={{ color: "var(--color-danger)" }}
                            >
                              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                            </button>
                          ) : null}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="flex items-start gap-3 p-4">
        <Calculator className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
        <p className="text-xs leading-relaxed text-muted">
          The calculator excludes income tax, FX movement, storage and wastage beyond the return
          allowance. Supplier GST registration, tariff classification and marketplace fees should be
          confirmed before committing stock.
        </p>
      </Card>

      {saveOpen ? (
        <SaveScenarioDialog
          inputs={toPayload(values)}
          onClose={() => setSaveOpen(false)}
          onSaved={(name) => {
            setSaveOpen(false);
            setNotice({ message: `Saved “${name}”.`, tone: "ok" });
            scenarios.reload();
          }}
        />
      ) : null}
    </div>
  );
}

function SaveScenarioDialog({
  inputs,
  onClose,
  onSaved,
}: {
  inputs: ProfitInputs;
  onClose: () => void;
  onSaved: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed.length < 2) {
      setError("Give the scenario a name of at least two characters.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post("/profit/scenarios", { name: trimmed, inputs });
      onSaved(trimmed);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Save scenario"
      description="The inputs and the current calculation are stored together, so reloading shows exactly what was saved."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-3">
        <Field id="scenario-name" label="Scenario name">
          <input
            id="scenario-name"
            className="field"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={160}
            placeholder="e.g. Silicone tray — supplier B quote"
            autoFocus
          />
        </Field>
        {error ? (
          <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
            {error}
          </p>
        ) : null}
        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-sm btn-primary" disabled={busy}>
            {busy ? "Saving…" : "Save scenario"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
