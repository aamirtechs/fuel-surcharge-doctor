# Good first issues

Seeded issues for new contributors. File each one on GitHub with the
`good first issue` and `help wanted` labels.

## 1. Add a DOE price table mode

Let `--method table` accept a JSON table of diesel price bands mapped
to surcharge percents (the way many carrier schedules work), and pick
the band for each load's diesel price. Add tests for band boundaries
and for a price below the lowest band.

## 2. Support CSV input

Accept a CSV file with columns load_id, miles, linehaul,
diesel_price, billed_fsc, so dispatchers can feed a spreadsheet
export directly. Missing optional columns must not break the run.

## 3. Add a per-carrier summary

Add a `--group-by` option (for example carrier or driver) that prints
subtotal rows per group in the text report and groups the JSON
output. Keep the overall summary unchanged.

## 4. Add a weekly diesel price fetch

Add an optional `--diesel-week` flag that reads a local JSON file of
weekly diesel prices (date to price) and uses the price for each
load's pickup week. No network calls: the file is supplied by the
user, so the tool stays offline and dependency free.
