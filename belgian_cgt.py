# belgian_cgt.py

# ─────────────────────────────────────────────────────────────
# TAX REGIME CONSTANTS
# ─────────────────────────────────────────────────────────────
# Defines the core parameters of the Belgian Capital Gains Tax model.

# --- Tax Rates ---
CGT_RATE             = 0.10         # 10% flat rate on net capital gains.
INTEREST_RATE        = 0.30         # 30% rate on the interest component of bond funds (Reynders Tax).
TOB_RATES            = {            # Tax on Stock Exchange Transactions (TOB) rates.
    'standard': 0.0035,             # For standard assets like stocks.
    'fund':     0.0132,             # For investment funds.
    'other':    0.0012              # For other specific assets.
}

# --- Key Dates & Thresholds ---
CUTOFF_DATE          = 2026-01-01   # The date the tax regime becomes effective.
BASE_EXEMPTION_2026  = 10_000         # The personal exemption amount for the inaugural year (€).
MAX_EXEMPTION_2026   = 15_000         # The maximum possible personal exemption in a year, including carry-forward (€).
CARRY_INCREMENT      = 1_000          # The maximum amount of unused exemption that can be carried forward (€).
WASH_WINDOW_DAYS     = 30             # The window (in days) before and after a sale to check for wash sales.

# --- Inflation Indexation ---
BASE_CPI             = 128.10         # The reference "health index" from December 2025.
CPI                  = {2025:128.10, 2026:131.20, 2027:134.50, 2028:138.00} # Yearly CPI values.

# --- Grandfathering ---
FMV_31DEC2025 = {} # Holds the Fair Market Value of assets on Dec 31, 2025, for the step-up basis rule.
                   # Example: {'isin_1': 105.50, 'isin_2': 2200.00}

# ─────────────────────────────────────────────────────────────
# SECURITY SIMILARITY (FOR WASH SALES)
# ─────────────────────────────────────────────────────────────
def similarity_key(info):
    """
    Generates a unique key to determine if two securities are "substantially identical"
    for the purpose of the wash sale rule.

    The method is hierarchical:
    1.  If a security tracks a formal index, its benchmark ID is used as the key.
        This is the most reliable method (e.g., two S&P 500 ETFs are identical).
    2.  If no benchmark exists, it creates a "fingerprint" by hashing the security's
        top holdings. This requires a 100% match of the provided holdings.
    """
    if info.benchmark_id:
        return "BMK::" + info.benchmark_id
    # The hash of a frozenset provides a unique, order-independent fingerprint
    # of the asset's holdings. Note: This implies a 100% match is required,
    # not a percentage overlap as might be used in more complex systems.
    return "FP::" + hash(frozenset(info.top_holdings))

# ─────────────────────────────────────────────────────────────
# ANNUAL EXEMPTION TRACKER
# ─────────────────────────────────────────────────────────────
class ExemptionTracker:
    """
    Manages the state of a taxpayer's annual exemption, including inflation
    indexation and the carry-forward of unused amounts.
    """
    carry = 0  # The amount of unused exemption carried forward from previous years.
               # Stored in 2026 euros and indexed when used.

    def _indexed(amount, year):
        """Indexes a 2026-euro amount to its equivalent value in a target year."""
        return amount * (CPI[year] / BASE_CPI)

    def per_person_cap(year):
        """Returns the maximum possible exemption for a person in a given year, indexed."""
        return _indexed(MAX_EXEMPTION_2026, year)

    def annual_base(year):
        """Returns the base annual exemption for a given year, indexed."""
        return _indexed(BASE_EXEMPTION_2026, year)

    def clamp_carry(year):
        """Ensures the carried-forward amount doesn't create a total exemption
        exceeding the indexed annual cap."""
        max_carry = per_person_cap(year) - annual_base(year)
        carry = min(carry, max_carry)

    def available(year, marital):
        """
        Calculates the total available exemption for a taxpayer in a given year.
        For couples, the final per-person amount is doubled.
        """
        clamp_carry(year)
        per_person_total = annual_base(year) + carry
        per_person_total = min(per_person_total, per_person_cap(year))
        multiplier = 2 if marital == 'couple' else 1
        return per_person_total * multiplier

    def update_carry(unused, year):
        """
        Updates the carry-forward balance for the next year based on the
        unused exemption from the current year.
        """
        max_carry_next_year = per_person_cap(year + 1) - annual_base(year + 1)
        # The increment is the smallest of: the €1k limit, the actual unused amount,
        # or the remaining room under next year's cap.
        increment = min(CARRY_INCREMENT, unused, max_carry_next_year - carry)
        carry = min(carry + increment, max_carry_next_year)

# ─────────────────────────────────────────────────────────────
# PORTFOLIO LOGIC & GAIN CALCULATION
# ─────────────────────────────────────────────────────────────
def find_wash_sale_replacement_lot(loss_tx, all_transactions):
    """
    Finds the first replacement lot purchased within the 30-day wash sale window.

    It searches all transactions for a 'BUY' of a substantially identical
    security within 30 days (before or after) the date of the loss-making sale.
    """
    key = similarity_key(loss_tx.security_info)
    loss_date = loss_tx.date

    # Find the first chronological purchase within the window.
    for tx in all_transactions:
        if tx.type != "BUY":
            continue
        if similarity_key(tx.security_info) != key:
            continue

        # Check if the purchase is within the 61-day window (-30 days, +30 days)
        if abs(days_between(tx.date, loss_date)) <= WASH_WINDOW_DAYS:
            # We found a replacement purchase. Return the lot associated with it.
            # The `lot` object is what holds the mutable state (like cost_basis).
            return tx.lot

    return None # No replacement lot found in the window.

def realised_gain(tx, portfolio, all_transactions):
    """
    Calculates the realised capital gain and interest income from a SELL transaction.

    This function orchestrates several key pieces of tax logic:
    - Applies the First-In, First-Out (FIFO) lot identification method.
    - Separates interest income from capital gain for bond funds.
    - Calculates and deducts transaction costs (TOB) from proceeds.
    - Applies the step-up basis rule for pre-2026 assets.
    - Identifies wash sales and defers the loss by adjusting the basis of the
      replacement lot.
    """
    # 1. Separate interest from capital proceeds for bond funds.
    interest_income = tx.interest_component if hasattr(tx, 'interest_component') else 0

    # 2. Calculate sale-side TOB and determine net capital proceeds.
    # The cost basis of a lot is assumed to already include purchase-side TOB.
    tob_rate = TOB_RATES.get(tx.tob_regime, 0)
    gross_proceeds = tx.qty * tx.price_per_unit
    sale_tob = gross_proceeds * tob_rate
    capital_proceeds = gross_proceeds - interest_income - sale_tob

    # 3. Identify lots to sell using FIFO logic.
    lots_to_sell = portfolio[tx.asset_id]
    sold_lot_info = []
    qty_remaining_to_sell = tx.qty

    for lot in list(lots_to_sell):  # Iterate over a copy to allow modification.
        if qty_remaining_to_sell <= 0: break

        sell_qty = min(lot.qty, qty_remaining_to_sell)

        # Determine the correct cost basis, applying the step-up rule if applicable.
        basis = lot.cost_basis_per_unit
        if lot.acquired < CUTOFF_DATE:
            basis = max(basis, FMV_31DEC2025.get(tx.asset_id, basis))

        sold_lot_info.append({'qty': sell_qty, 'basis': basis})

        # Update portfolio state.
        lot.qty -= sell_qty
        qty_remaining_to_sell -= sell_qty
        if lot.qty == 0:
            lots_to_sell.remove(lot)

    # 4. Calculate the total gain from the sold lots.
    gain = 0
    avg_sale_price_per_unit = capital_proceeds / tx.qty
    for info in sold_lot_info:
        gain += (avg_sale_price_per_unit - info['basis']) * info['qty']

    # 5. Handle wash sales: if a loss is realised, defer it.
    if gain < 0:
        replacement_lot = find_wash_sale_replacement_lot(tx, all_transactions)
        if replacement_lot:
            # Add the disallowed loss to the cost basis of the replacement lot.
            disallowed_loss = abs(gain)
            replacement_lot.cost_basis_per_unit += (disallowed_loss / replacement_lot.qty)
            gain = 0  # The loss is deferred, not realised in the current year.

    return gain, interest_income

# ─────────────────────────────────────────────────────────────
# EXIT TAX CALCULATION
# ─────────────────────────────────────────────────────────────
def calculate_exit_tax(portfolio, exit_date, fmv_on_date):
    """
    Calculates the exit tax on unrealised gains upon moving abroad.
    This is treated as a "deemed disposal" of all assets.
    """
    unrealised_gains = 0
    exit_fmv = fmv_on_date[exit_date]

    for asset_id, lots in portfolio.items():
        for lot in lots:
            # Apply the same step-up basis logic as for realised gains.
            basis = lot.cost
            if lot.acquired < CUTOFF_DATE:
                basis = max(basis, FMV_31DEC2025[asset_id])

            # If no FMV is available on exit, assume no gain for that asset.
            fmv_per_unit = exit_fmv.get(asset_id, basis)
            gain = (fmv_per_unit - basis) * lot.qty

            # Only positive gains are summed for the exit tax; losses are ignored.
            if gain > 0:
                unrealised_gains += gain

    # Note: The model assumes the annual exemption does not apply to the exit tax.
    # This is a critical policy point that would require clarification.
    return round(unrealised_gains * CGT_RATE, 2)

# ─────────────────────────────────────────────────────────────
# MAIN TAX CALCULATION ORCHESTRATOR
# ─────────────────────────────────────────────────────────────
def belgian_cgt(transactions, marital='single', residency_status=None, fmv_on_date=None):
    """
    Calculates the total annual Belgian capital gains tax liability.

    This function processes all transactions for a taxpayer, calculates realised
    gains/losses and interest income, and then applies the tax rules for each
    year, including exemptions and the exit tax upon change of residency.
    """
    txs = sort_by_date(transactions)
    realised_gains_by_year = defaultdict(float)
    interest_income_by_year = defaultdict(float)
    tax_due_by_year = defaultdict(float)
    tracker = ExemptionTracker()
    portfolio = defaultdict(list)  # Tracks all currently held asset lots.

    # --- Phase 1: Process all transactions to build annual gain/loss figures ---
    for tx in txs:
        if tx.date.year < 2026: continue

        if tx.type == "BUY":
            # Assumes tx.lot is a pre-constructed object with all necessary info.
            portfolio[tx.asset_id].append(tx.lot)
        elif tx.type == "SELL":
            year = tx.date.year
            # Pass the full transaction list to handle wash sale lookups.
            gain, interest = realised_gain(tx, portfolio, txs)
            realised_gains_by_year[year] += gain
            interest_income_by_year[year] += interest

    # --- Phase 2: Calculate tax liability for each year ---
    all_years = sorted(list(set(realised_gains_by_year.keys()) | set(residency_status.keys())))
    for year in all_years:
        # Step 1: Apply the 30% Reynders Tax on bond fund interest.
        interest_tax = interest_income_by_year.get(year, 0) * INTEREST_RATE
        tax_due_by_year[year] += round(interest_tax, 2)

        # Step 2: Apply the 10% CGT on net realised capital gains.
        net_gain = realised_gains_by_year.get(year, 0)
        exempt = tracker.available(year, marital)
        taxable_gain = max(0, net_gain - exempt)
        tax_due_by_year[year] += round(taxable_gain * CGT_RATE, 2)

        # Update the exemption carry-forward for the next year.
        unused_exemption = max(0, exempt - net_gain)
        tracker.update_carry(unused_exemption, year)

        # Step 3: Check for and apply the Exit Tax if residency changes.
        is_resident_start = residency_status.get(year, "BE") == "BE"
        is_resident_end = residency_status.get(year + 1, "BE") == "BE"

        if is_resident_start and not is_resident_end:
            exit_date = f"{year}-12-31"  # Assume exit occurs at year-end.
            exit_tax_amount = calculate_exit_tax(portfolio, exit_date, fmv_on_date)
            tax_due_by_year[year] += exit_tax_amount

    return tax_due_by_year