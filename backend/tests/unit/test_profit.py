from decimal import Decimal

import pytest

from app.services.profit import (
    ASSUMPTIONS_VERSION,
    DISCLAIMER,
    ProfitInputError,
    calculate,
    normalise_inputs,
)


def test_default_calculation_is_decimal_exact():
    result = calculate()
    outputs = result["outputs"]

    # 69.95 / 1.10 = 63.5909; landed cost = 12.40 + 3.10.
    assert outputs["selling_price_ex_gst"] == "63.59"
    assert outputs["landed_cost_ex_gst"] == "15.50"
    assert outputs["landed_cost_cash"] == "17.05"
    assert outputs["gst_on_landed_cost"] == "1.55"
    assert outputs["gst_remitted_per_sale"] == "6.36"
    assert outputs["gross_profit"] == "48.09"
    assert outputs["payment_fees"] == "1.52"
    assert outputs["returns_allowance"] == "2.10"
    assert outputs["contribution_margin"] == "34.77"
    assert outputs["break_even_ad_cost"] == "34.77"
    assert outputs["profit_per_order"] == "22.77"
    assert outputs["monthly"][0]["profit"] == "2276.83"
    assert outputs["monthly"][0]["revenue_ex_gst"] == "6359.09"
    assert result["assumptions_version"] == ASSUMPTIONS_VERSION
    assert result["disclaimer"] == DISCLAIMER


def test_all_money_outputs_are_two_decimal_strings():
    outputs = calculate()["outputs"]
    for key, value in outputs.items():
        if key.endswith("_pct") or key == "monthly":
            continue
        assert isinstance(value, str), key
        assert Decimal(value) == Decimal(value).quantize(Decimal("0.01")), key


def test_import_duty_increases_landed_cost():
    base = calculate()
    dutiable = calculate({"import_duty_rate_pct": 5})
    assert Decimal(dutiable["outputs"]["landed_cost_ex_gst"]) > Decimal(
        base["outputs"]["landed_cost_ex_gst"]
    )
    # 5% of (12.40 + 3.10) = 0.775 -> 0.78 rounded half-up.
    assert dutiable["outputs"]["landed_cost_ex_gst"] == "16.28"


def test_supplier_gst_is_recoverable_when_claimed():
    claimed = calculate({"supplier_charges_gst": True})["outputs"]
    unclaimed = calculate(
        {"supplier_charges_gst": True, "claim_input_tax_credit": False}
    )["outputs"]

    # 12.40 inc GST is 11.27 ex GST, so the cost basis is lower when it is claimed.
    assert claimed["landed_cost_ex_gst"] == "14.37"
    assert Decimal(claimed["profit_per_order"]) > Decimal(unclaimed["profit_per_order"])


def test_unregistered_operator_does_not_remit_gst():
    outputs = calculate({"gst_registered": False})["outputs"]
    assert outputs["selling_price_ex_gst"] == "69.95"
    assert outputs["gst_remitted_per_sale"] == "0.00"
    assert outputs["gst_on_landed_cost"] == "0.00"


def test_warnings_name_the_uncertain_assumptions():
    result = calculate({"import_duty_rate_pct": 0, "return_rate_pct": 0})
    joined = " ".join(result["warnings"])
    assert "Import duty" in joined
    assert "Returns are provisioned" not in joined


def test_unknown_input_is_rejected():
    with pytest.raises(ProfitInputError):
        calculate({"supplier_price": "10", "magic_discount": "5"})


def test_negative_and_out_of_range_values_are_rejected():
    with pytest.raises(ProfitInputError):
        calculate({"supplier_price": "-1"})
    with pytest.raises(ProfitInputError):
        calculate({"selling_price_inc_gst": "0"})
    with pytest.raises(ProfitInputError):
        calculate({"gst_rate_pct": 101})
    with pytest.raises(ProfitInputError):
        calculate({"payment_fee_pct": -1})


def test_volumes_must_be_whole_numbers():
    with pytest.raises(ProfitInputError):
        calculate({"monthly_order_volumes": [10.5]})
    with pytest.raises(ProfitInputError):
        calculate({"monthly_order_volumes": "100,500"})


def test_volumes_are_capped_and_zero_is_kept():
    normalised = normalise_inputs({"monthly_order_volumes": [0, 10] + [1] * 20})
    assert normalised["monthly_order_volumes"][:2] == [0, 10]
    assert len(normalised["monthly_order_volumes"]) == 12


def test_normalise_inputs_merges_defaults_and_normalises_currency():
    normalised = normalise_inputs({"currency": "aud", "supplier_price": "10"})
    assert normalised["currency"] == "AUD"
    assert normalised["supplier_price"] == "10.00"
    assert normalised["gst_rate_pct"] == 10.0
