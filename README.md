# Belgian Capital Gains Tax (CGT) - A Python Model

This repository contains a Python script (`belgian_cgt.py`) that models a proposed Belgian Capital Gains Tax (CGT). This document serves as a README, explaining the rules and calculations implemented in the model.

## 1. Core Tax Principles

The framework is defined by a set of core principles governing tax rates, timing, and calculation methods.

*   **Tax Rates:** The system employs two distinct flat rates:
    *   **Capital Gains:** **10%** on net taxable capital gains ([`CGT_RATE`](belgian_cgt.py:9)).
    *   **Interest Income:** **30%** on the interest component of bond funds (see Reynders Tax, section 4.2) ([`INTEREST_RATE`](belgian_cgt.py:10)).

*   **Taxable Event:** Tax is levied upon the **realization** of a gain, which occurs when an asset is sold.

*   **Effective Date:** The regime applies to all transactions occurring on or after **January 1, 2026** ([`CUTOFF_DATE`](belgian_cgt.py:18)).

*   **Netting of Gains & Losses:** Within a calendar year, all realized capital gains and losses are netted. The annual exemption is applied only against a resulting net gain.

## 2. Calculation of Realised Gains

The gain or loss on a sale is the difference between the net proceeds and the adjusted cost basis of the asset.

`Gain/Loss = Net Sale Proceeds - Adjusted Cost Basis`

### 2.1. Adjusted Cost Basis

The cost basis is the original purchase price, adjusted for any associated transaction costs.
*   **Transaction Costs:** The basis includes all purchase fees, most notably the **Tax on Stock Exchange Transactions (TOB)**.

### 2.2. Net Sale Proceeds

These are the gross proceeds from a sale, reduced by any selling costs.
*   **Transaction Costs:** The sale-side **TOB** is deducted from the gross proceeds to determine the net amount used for the gain calculation ([`realised_gain`](belgian_cgt.py:147-152)).

### 2.3. Asset & Lot Identification Rules

*   **Lot Identification (FIFO):** When selling a portion of a holding acquired at different times, the **First-In, First-Out (FIFO)** method is mandatory. The first assets purchased are deemed to be the first assets sold ([`realised_gain`](belgian_cgt.py:154-176)).

*   **Step-Up Basis (Grandfathering):** For assets acquired before the `CUTOFF_DATE`, the cost basis is the **higher** of the original adjusted cost or the Fair Market Value (FMV) on December 31, 2025. If no FMV is recorded for an asset, its original cost basis is used. This rule ensures that gains accrued before the tax regime's existence are not taxed ([`realised_gain`](belgian_cgt.py:166-168)).

## 3. Annual Personal Exemption

An inflation-indexed personal exemption is available each year to reduce net capital gains.

*   **Base Amount:** **€10,000** per person for the year 2026 ([`BASE_EXEMPTION_2026`](belgian_cgt.py:19)).

*   **Inflation Indexation:** All exemption thresholds are indexed annually using a reference CPI, with December 2025 as the baseline ([`_indexed`](belgian_cgt.py:64)).

*   **Annual Cap:** The total exemption in a single year cannot exceed an indexed **€15,000** per person ([`MAX_EXEMPTION_2026`](belgian_cgt.py:20)).

*   **Carry-Forward of Unused Amounts:**
    *   Up to **€1,000** of unused exemption can be carried forward to the next year ([`CARRY_INCREMENT`](belgian_cgt.py:21)).
    *   The total carried-forward balance is itself capped to ensure the total exemption never exceeds the annual €15,000 limit ([`clamp_carry`](belgian_cgt.py:76)).

*   **Marital Status:** For couples, the final, capped per-person exemption is **doubled** ([`available`](belgian_cgt.py:82)).

## 4. Special Regimes & Scenarios

### 4.1. Tax on Stock Exchange Transactions (TOB)

The TOB is a tax on the transaction itself and is treated as a direct cost, thereby impacting the capital gain calculation.

*   **Regimes:** The model includes three TOB rates based on asset type (`standard`, `fund`, `other`) ([`TOB_RATES`](belgian_cgt.py:11)).
*   **Impact on CGT:** The TOB is factored into the `Adjusted Cost Basis` on purchase and the `Net Sale Proceeds` on sale.

### 4.2. Reynders Tax (Bond Funds)

The system incorporates a specific tax treatment for bond funds, separating the return into two components.
*   **Interest Component:** The portion of the gain attributable to accrued interest is taxed at the **30%** interest income rate.
*   **Capital Gain Component:** The remaining portion (price appreciation) is treated as a standard capital gain, subject to the **10%** CGT rate and eligible for the annual exemption.

### 4.3. Wash Sale Rule

This rule prevents realizing a loss for tax purposes while maintaining economic exposure to an asset.

*   **Definition:** A wash sale occurs if a security is sold at a loss and a "substantially identical" security is purchased within a **30-day window** (before or after the sale) ([`WASH_WINDOW_DAYS`](belgian_cgt.py:22)).

*   **Security "Sameness":** A security is considered substantially identical if it shares the same **benchmark ID** or has a **100% identical holdings fingerprint** ([`similarity_key`](belgian_cgt.py:46)).

*   **Tax Consequence:** The loss is disallowed in the current year. Instead, it is **added to the cost basis** of the replacement security, deferring the loss until that new security is sold ([`realised_gain`](belgian_cgt.py:184-190)). The system identifies the **first chronological purchase** within the 30-day window as the replacement lot ([`find_wash_sale_replacement_lot`](belgian_cgt.py:107)).

### 4.4. Exit Tax (Deemed Disposal)

A tax is levied on unrealised gains when a taxpayer ceases to be a Belgian resident.

*   **Trigger:** A change in residency status from Belgian to non-Belgian ([`belgian_cgt`](belgian_cgt.py:274-277)).

*   **Calculation:** The event is treated as a "deemed disposal" of all assets at their Fair Market Value. The tax is calculated on the sum of all *positive* unrealised gains; losses are ignored. If an asset's FMV is not available on the exit date, it is assumed to be equal to its basis, resulting in no gain for that asset. The step-up basis rule also applies ([`calculate_exit_tax`](belgian_cgt.py:197)).

*   **Exemption Non-Applicability:** The model assumes the annual personal exemption **cannot** be used to offset gains subject to the exit tax ([`calculate_exit_tax`](belgian_cgt.py:220-222)).