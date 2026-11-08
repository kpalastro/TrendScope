"""GST-aware profit calculator.

The calculator is deliberately separate from the profitability *score*: the
score uses fixed assumptions to rank products, while this module lets an
operator test a real supplier quote. Every monetary output is a decimal string
so the arithmetic is auditable and never passes through a binary float.

Model
-----
* ``landed_cost_ex_gst`` removes recoverable GST from the supplier price and
  adds international shipping and import duty.
* ``landed_cost_cash`` is the actual invoice outflow. It includes supplier GST
  and, when the operator is GST-registered, import GST on the landed value.
* The cost basis for margin is the ex-GST landed cost when input tax credits
  are claimable; otherwise GST is a real cost and the cash landed cost is used.
* Revenue excludes GST only when the operator is registered; otherwise the
  selling price is the revenue and no GST is remitted.
* Contribution subtracts fulfilment, packaging, payment fees and the expected
  cost of returns. Advertising is reported separately as ``break_even_ad_cost``
  (the ad spend at which profit is zero) and deducted for ``profit_per_order``.

All calculations are estimates. They exclude income tax, FX movement, storage
and wastage beyond the return allowance.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

ASSUMPTIONS_VERSION = "2026-11"

DISCLAIMER = (
    "Estimate only. Excludes income tax, FX movement, storage and wastage beyond the "
    "return allowance. Confirm supplier GST registration, tariff classification and "
    "marketplace fees before committing stock."
)

DEFAULTS: dict[str, object] = {
    "currency": "AUD",
    "supplier_price": "12.40",
    "international_shipping": "3.10",
    "import_duty_rate_pct": 0.0,
    "supplier_charges_gst": False,
    "gst_registered": True,
    "gst_rate_pct": 10.0,
    "claim_input_tax_credit": True,
    "domestic_fulfilment": "8.50",
    "packaging": "1.20",
    "payment_fee_pct": 1.75,
    "payment_fee_fixed": "0.30",
    "advertising_cost_per_order": "12.00",
    "selling_price_inc_gst": "69.95",
    "return_rate_pct": 3.0,
    "monthly_order_volumes": [100, 500, 1000, 5000],
}

MAX_ORDER_VOLUME = 10_000_000


class ProfitInputError(ValueError):
    """Raised when an input cannot produce a meaningful calculation."""


def _decimal(value: object, field: str, *, minimum: Decimal | None = None) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ProfitInputError(f"{field} must be a number.") from exc
    if not parsed.is_finite():
        raise ProfitInputError(f"{field} must be a finite number.")
    if minimum is not None and parsed < minimum:
        raise ProfitInputError(f"{field} must be at least {minimum}.")
    return parsed


def _percent(value: object, field: str) -> Decimal:
    parsed = _decimal(value, field, minimum=Decimal("0"))
    if parsed > 100:
        raise ProfitInputError(f"{field} must be between 0 and 100.")
    return parsed


def _positive_decimal(value: object, field: str) -> Decimal:
    parsed = _decimal(value, field, minimum=Decimal("0"))
    if parsed <= 0:
        raise ProfitInputError(f"{field} must be greater than zero.")
    return parsed


def _money(value: Decimal) -> str:
    """Two-decimal string, half-up, independent of the float formatter."""

    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _pct(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _volumes(value: object) -> list[int]:
    if value is None:
        return list(DEFAULTS["monthly_order_volumes"])
    if not isinstance(value, (list, tuple)):
        raise ProfitInputError("monthly_order_volumes must be a list of order counts.")
    volumes: list[int] = []
    for item in value:
        parsed = _decimal(item, "monthly_order_volumes", minimum=Decimal("0"))
        if parsed != parsed.to_integral_value():
            raise ProfitInputError("monthly_order_volumes must contain whole order counts.")
        count = int(parsed)
        if count > MAX_ORDER_VOLUME:
            raise ProfitInputError(
                f"monthly_order_volumes cannot exceed {MAX_ORDER_VOLUME:,} per entry."
            )
        volumes.append(count)
    return volumes[:12]


def normalise_inputs(payload: dict | None = None) -> dict:
    """Merge with defaults and validate types. Returns JSON-safe values."""

    supplied = payload or {}
    unknown = set(supplied) - set(DEFAULTS)
    if unknown:
        raise ProfitInputError(f"Unknown input(s): {', '.join(sorted(unknown))}.")

    merged = {**DEFAULTS, **{key: value for key, value in supplied.items() if value is not None}}
    normalised = {
        "currency": str(merged["currency"]).upper()[:3],
        "supplier_price": _money(_positive_decimal(merged["supplier_price"], "supplier_price")),
        "international_shipping": _money(
            _decimal(merged["international_shipping"], "international_shipping", minimum=Decimal("0"))
        ),
        "import_duty_rate_pct": _pct(
            _percent(merged["import_duty_rate_pct"], "import_duty_rate_pct")
        ),
        "supplier_charges_gst": bool(merged["supplier_charges_gst"]),
        "gst_registered": bool(merged["gst_registered"]),
        "gst_rate_pct": _pct(_percent(merged["gst_rate_pct"], "gst_rate_pct")),
        "claim_input_tax_credit": bool(merged["claim_input_tax_credit"]),
        "domestic_fulfilment": _money(
            _decimal(merged["domestic_fulfilment"], "domestic_fulfilment", minimum=Decimal("0"))
        ),
        "packaging": _money(_decimal(merged["packaging"], "packaging", minimum=Decimal("0"))),
        "payment_fee_pct": _pct(_percent(merged["payment_fee_pct"], "payment_fee_pct")),
        "payment_fee_fixed": _money(
            _decimal(merged["payment_fee_fixed"], "payment_fee_fixed", minimum=Decimal("0"))
        ),
        "advertising_cost_per_order": _money(
            _decimal(
                merged["advertising_cost_per_order"],
                "advertising_cost_per_order",
                minimum=Decimal("0"),
            )
        ),
        "selling_price_inc_gst": _money(
            _positive_decimal(merged["selling_price_inc_gst"], "selling_price_inc_gst")
        ),
        "return_rate_pct": _pct(_percent(merged["return_rate_pct"], "return_rate_pct")),
        "monthly_order_volumes": _volumes(merged["monthly_order_volumes"]),
    }
    return normalised


def calculate(payload: dict | None = None) -> dict:
    inputs = normalise_inputs(payload)

    supplier_price = Decimal(inputs["supplier_price"])
    shipping = Decimal(inputs["international_shipping"])
    duty_rate = Decimal(str(inputs["import_duty_rate_pct"])) / Decimal("100")
    gst_rate = Decimal(str(inputs["gst_rate_pct"])) / Decimal("100")
    fulfilment = Decimal(inputs["domestic_fulfilment"])
    packaging = Decimal(inputs["packaging"])
    fee_pct = Decimal(str(inputs["payment_fee_pct"])) / Decimal("100")
    fee_fixed = Decimal(inputs["payment_fee_fixed"])
    advertising = Decimal(inputs["advertising_cost_per_order"])
    selling_inc = Decimal(inputs["selling_price_inc_gst"])
    return_rate = Decimal(str(inputs["return_rate_pct"])) / Decimal("100")

    gst_registered = inputs["gst_registered"]
    supplier_charges_gst = inputs["supplier_charges_gst"]

    supplier_ex = supplier_price / (1 + gst_rate) if supplier_charges_gst else supplier_price
    duty = (supplier_ex + shipping) * duty_rate
    landed_ex = supplier_ex + shipping + duty

    # Cash outflow: the supplier's invoice, plus import GST when registered.
    import_gst = landed_ex * gst_rate if gst_registered else Decimal("0")
    landed_cash = supplier_ex + shipping + duty + import_gst
    if supplier_charges_gst:
        # supplier_ex already excludes the supplier's GST; add it back for cash.
        landed_cash += supplier_price - supplier_ex

    claim_itc = gst_registered and inputs["claim_input_tax_credit"]
    cost_basis = landed_ex if claim_itc else landed_cash

    if gst_registered:
        revenue = selling_inc / (1 + gst_rate)
        gst_remitted = selling_inc - revenue
    else:
        revenue = selling_inc
        gst_remitted = Decimal("0")

    gross_profit = revenue - cost_basis
    fees = selling_inc * fee_pct + fee_fixed
    returns = selling_inc * return_rate
    contribution = gross_profit - fulfilment - packaging - fees - returns
    profit = contribution - advertising

    gross_margin_pct = (gross_profit / revenue * 100) if revenue else None
    contribution_margin_pct = (contribution / revenue * 100) if revenue else None

    monthly = []
    for orders in inputs["monthly_order_volumes"]:
        monthly.append(
            {
                "orders": orders,
                "revenue_ex_gst": _money(revenue * orders),
                "gross_profit": _money(gross_profit * orders),
                "advertising_spend": _money(advertising * orders),
                "profit": _money(profit * orders),
            }
        )

    warnings: list[str] = []
    if supplier_charges_gst and not inputs["claim_input_tax_credit"]:
        warnings.append(
            "GST charged by the supplier is treated as a cost because no input tax "
            "credit is being claimed."
        )
    if not gst_registered:
        warnings.append(
            "GST is not remitted on sales, and GST paid on imports is a real cost. "
            "Register for GST before treating the selling price as GST-inclusive."
        )
    if inputs["import_duty_rate_pct"] == 0:
        warnings.append(
            "Import duty is set to 0%. Confirm the tariff classification before relying "
            "on this margin."
        )
    if inputs["return_rate_pct"] > 0:
        warnings.append(
            f"Returns are provisioned at {inputs['return_rate_pct']:.2f}% of the "
            "GST-inclusive selling price."
        )

    return {
        "inputs": inputs,
        "assumptions_version": ASSUMPTIONS_VERSION,
        "outputs": {
            "landed_cost_ex_gst": _money(landed_ex),
            "landed_cost_cash": _money(landed_cash),
            "gst_on_landed_cost": _money(import_gst),
            "selling_price_ex_gst": _money(revenue),
            "gst_remitted_per_sale": _money(gst_remitted),
            "gross_profit": _money(gross_profit),
            "gross_margin_pct": _pct(gross_margin_pct),
            "payment_fees": _money(fees),
            "returns_allowance": _money(returns),
            "contribution_margin": _money(contribution),
            "contribution_margin_pct": _pct(contribution_margin_pct),
            "break_even_ad_cost": _money(contribution),
            "advertising_cost_per_order": _money(advertising),
            "profit_per_order": _money(profit),
            "profit_margin_pct": _pct((profit / revenue * 100) if revenue else None),
            "monthly": monthly,
        },
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }
