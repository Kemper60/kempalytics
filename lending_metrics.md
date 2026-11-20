# Metrics, Definitions & Data Limitations

This file records the scope rules, metric definitions, assumptions, and known data
limitations for the analysis. Every number in the README should be traceable to a
definition here.

---

## 1. Data Sources

| Table | Source file | Description | Rows loaded | Rows rejected at load |
|---|---|---|---|---|
| `raw_accepted` | `accepted_2007_to_2018Q4.csv.gz` | Booked Lending Club loans, one row per loan, with final status | 2,260,701 rows   151 cols         0 rejected  (68.0s) |

| `raw_rejected` | `rejected_2007_to_2018Q4.csv.gz` | Declined loan applications | 27,648,741 rows     9 cols 0 rejected  (35.7s)|

- **Origin:** Kaggle dataset "Lending Club Loan Data" (wordsforthewise), downloaded with `kagglehub`.
- **Coverage:** 2007 through 2018 Q4.
- **Database:** stored locally at `data/lending.duckdb`, which is excluded from Git.

---

## 2. Analysis Scope (`loans_scoped`)

| Rule | Value | Rationale |
|---|---|---|
| Loan term | 36 months only | Keeps one product type with consistent loss timing |
| Issue dates | January 2012 – December 2015 | Every loan in the window had reached maturity by the end of the data (Dec 2018), so outcomes are final and loss rates aren't understated by loans that are still open |
| Loan status | Fully Paid, Charged Off, Default | Final outcomes only |
| Excluded | "Does not meet the credit policy. Status: …" loans | Originated outside Lending Club's standard credit policy, so they aren't representative of the core book |

**Rows in scope:** 589,488

---

## 3. Metric Definitions

### Loan-level fields
| Field | Definition |
|---|---|
| `issue_date` | `issue_d` parsed to a date (format `Mon-YYYY`, e.g., `Dec-2015`); falls on the first day of the issue month |
| `issue_qtr` | `issue_date` truncated to the first day of its quarter |
| `bad_flag` | **1** = Charged Off or Default; **0** = Fully Paid |
| `fico_mid` | (`fico_range_low` + `fico_range_high`) / 2 |

### Portfolio metrics
| Metric | Definition |
|---|---|
| **Bad rate** | Share of loans with `bad_flag` = 1; mean of `bad_flag` across loans in scope. Overall: 43% |
| **Applications** (quarter) | Accepted loans + rejected applications in the quarter |
| **Approvals** (quarter) | Accepted loans issued in the quarter |
| **Approval rate** | Approvals ÷ Applications |

### Field groups
| Group | Fields | Use |
|---|---|---|
| **Origination** (known at decision time) | `funded_amnt`, `loan_amnt`, `int_rate`, `grade`, `sub_grade`, FICO fields, `dti`, `annual_inc`, `emp_length`, `home_ownership`, `purpose`, `addr_state`, `revol_util`, `inq_last_6mths` | Allowed as model features and segmentation variables |
| **Outcome** (post-origination) | `loan_status`, `total_pymnt`, `recoveries`, `last_pymnt_d` | Used only to measure performance. **Never** used as model features, because that would leak future information into the model |

---

## 4. Data Quality Controls

`src/load_raw.py` runs these checks after every build. **The build fails if any of them returns a non-zero count.**

| Check | Result |
|---|---|
| Null `id`, `loan_amnt`, `grade`, `fico_mid`, `issue_date` | (0)
| Duplicate `id` | (0) |
| `funded_amnt` > `loan_amnt` | (0) |
| `fico_range_low` > `fico_range_high` | (0) |
| `int_rate` outside 0–50% | (0) |

Rows DuckDB couldn't parse at load are logged to the `load_rejects` table with line number and reason.

---

## 5. Known Limitations

1. **Approval rate covers every loan term.** The rejected-applications file has no loan term field, so the funnel counts accepted loans of every term, not only the 36-month scope. Restricting accepted loans to 36 months would understate the approval rate.
2. **Application date and issue date don't match exactly.** Rejected applications are dated by application date, while accepted loans are dated by issue date. A loan applied for late in one quarter may be issued in the next, so quarterly approval rates are approximate.
3. **Risk score in the rejected file.** The `Risk_Score` field may not use the same scoring model across the whole time period. Don't compare it directly with the accepted loans' FICO fields without checking.
4. **Junk rows in the raw file.** The raw accepted file contains summary or footer rows with a non-numeric `id` and null loan fields. The issue-date and status filters remove them from `loans_scoped`.
5. **Rows rejected at load.** 0 rows could not be parsed and were skipped; see `load_rejects`.
6. **Selection bias.** Performance data exists only for approved loans. Rejected applicants' outcomes are unknown, so any credit model reflects only Lending Club's past approval decisions.
7. **Product mix.** Lending Club makes unsecured personal installment loans. The methods carry over to credit cards, HELOCs, and auto loans, but the loss levels and timing do not.

---

## 6. Assumptions (to extend in later modules)

| Assumption | Value | Used in |
|---|---|---|
| Cost of funds | [e.g., 3%] | Module 3, risk-adjusted margin |
| Month of default | Months between `issue_d` and `last_pymnt_d` (approximation; the data has no monthly payment history) | Module 2, vintage curves |
| Stress multipliers | [Baseline 1.0x, mild 1.5x, severe 2.0x] | Module 5, scenarios |

---

### Module 1 Findings: Portfolio KPIs

**Question:** How big is the book, what's in it, and how is credit quality trending?

**Scope:** 36-month Lending Club loans issued 2012–2015 with final outcomes (589,488 loans, $7.5B funded). The approval rate covers all loan terms, because the rejected-applications file has no term field (see `METRICS.md`).

**Volume and approvals:**
- Quarterly originations grew from 6,498 loans ($77.3M) in 2012-Q1 to 88,669 loans ($1,127.5M) in 2015-Q4, about 14.6x growth.
- The approval rate rose slightly from 12.51% to 12.67%, as applications grew faster than approvals.
- The average loan size increased from $11,895.37 to $12,715.29, and the weighted average interest rate decreased from 11.86% to 10.72%.

**Grade mix:**
- The share of higher-risk grades (D–G) increased, from 11.6% of loans in 2012 to 12.8% in 2015, while grades A–B went from 70% to 61%, suggesting a deterioration in approval quality and heightened risk. This drop in quality could also help explain the significant increase in overall loans and dollars funded.

**Credit quality:**
- The overall bad rate is 14%, ranging from 5.4% for grade A to 4% for grade G.
- Bad rates fall steadily as FICO scores rise, from 18.3% in the 660-679 band to 5.2% at 840+.
- **Takeaway:** both grade and FICO rank risk cleanly, so the underwriting tiers separate good and bad borrowers as intended.

**Implication:**
- *Mix shifted riskier:* Growth came partly from riskier grades, which raises expected losses for the portfolio as a whole. Module 2 tests whether that explains any decline in performance over time.

### Module 2 Findings: Vintage Loss Curves

**Question:** Are newer loans performing worse than older loans at the same age, and if so, is that because of a shift in the borrower mix or a true decline in credit quality?

**Method:** For each issue-year vintage, the cumulative bad rate at each month on book (MOB) is the number of loans that had gone bad by that month divided by *all* loans in the vintage. The default month is approximated as the months from issue to the last payment date (see `METRICS.md`). Both charts use the same y-axis scale so they can be compared directly.

**All grades:**
- Later vintages perform worse. At MOB 24, the 2015 vintage's cumulative bad rate is 11.6%, compared with 10.45% for 2012.
- Final bad rates by vintage: 2012 13.5%, 2013 12.3%, 2014 13.65%, 2015 14.78%.

**Grades A–B only:**
- The gap between vintages shrinks about 4 points. At MOB 24, 2015 is at 6.65% vs 7.95% for 2012.

**Conclusion:**
- *Mix shift:* Most of the deterioration across the whole portfolio comes from a **shift in mix toward riskier grades** (see the grade-mix chart in Module 1). Within the same grade, credit performance held up. 
**Implication:** manage risk through origination mix and grade-level limits rather than tightening credit across the board.

### Module 3 Findings: Pricing and Risk-Adjusted Return

**Question:** Does the interest rate charged on each sub-grade cover that sub-grade's credit losses plus the cost of funding?

**Method:** For each sub-grade:
- **Annual loss rate:** (funded amount − total payments received) on bad loans ÷ total funded ÷ 3 years
- **Breakeven rate:** annual loss rate + 3% assumed cost of funds
- **Risk-adjusted margin:** average interest rate − breakeven rate

**Findings:**
- **Every sub-grade's interest rate is above breakeven** the minimum margin is 3.3% at sub-grade A1, indicating that higher grades have lower margins, likely due to low default probabilities and higher competition to lend to those borrowers
- **Margins widen as risk rises:** about 3.3-3.8% for grade A sub-grades, up to 7.4-9.8% for the riskiest (F-G).
- **Losses grow faster than rates:** from A1 to G5, interest rates rise about 4.6x, while annual loss rates rise about 21x.
- Sub-grades A-B have a margin under 7.6% and make up 59.4% of funded dollars.

**Implication:** The portfolio is priced to be profitable in every tier. The less risky sub-grades have narrower margins, however, riskier sub-grades have higher margins to account for the higher uncertainty present in those loans. Module 5 tests whether margins hold up when losses rise.

**Caveat:** The loss measure nets interest collected before default against principal lost, and the margin credits the full contractual rate. Both choices flatter the riskiest sub-grades, so real margins there are likely thinner than shown (see `METRICS.md`).


*Last updated: 11/19/2026*