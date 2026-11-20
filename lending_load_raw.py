"""
Purpose: Load the raw Lending Club CSVs into a local DuckDB database.
 
Run from the project root:
    python src/load_raw.py
 
Creates data/lending.duckdb with these tables:
    raw_accepted    - booked loans (one row per loan)
    raw_rejected    - declined applications
    load_rejects    - any CSV rows DuckDB could not parse, with the reason
    load_log        - row counts and timing for each load (audit trail)
"""
import time
from pathlib import Path
import kagglehub
 
import duckdb
 
# ---------------------------------------------------------------------------
# Configuration - edit the file names if your download differs
# ---------------------------------------------------------------------------
# Download latest version
path = kagglehub.dataset_download("wordsforthewise/lending-club")

print("Path to dataset files:", path)

PROJECT_ROOT = Path(__file__).resolve().parents[0]
DATA_DIR = PROJECT_ROOT / "data"       #define a subdirectory for the data
DATA_DIR.mkdir(exist_ok=True)          # create data/ if it isn't there yet

DB_PATH = DATA_DIR / "lending.duckdb" #define the DB path as the data folder

print(DB_PATH)

#list where the data sources are
SOURCES = {
    "raw_accepted": Path(path) / "accepted_2007_to_2018Q4.csv.gz",
    "raw_rejected": Path(path) / "rejected_2007_to_2018Q4.csv.gz",
}

def load_csv(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> None:

    #the purpose of this function is to load the raw data into the duckdb database

    #Check if this path exists and if not raise an error immediately
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Download the Kaggle files into data/ first.")
 
    start = time.perf_counter()   #start the timer
 
    # read_csv options:
    #   sample_size=-1     scan the WHOLE file before choosing column types, so a
    #                      messy value deep in the file can't break the type guess
    #   header=true        first row holds column names
    #   store_rejects=true don't crash on bad rows; skip them and log each one
    #                      (with the reason) so the skip is visible, not silent
    #   rejects_table/_scan where those logged bad rows go (one pair per table,
    #                      since DuckDB won't reuse the names within a session)
    # DuckDB decompresses .gz on the fly, so don't unzip the files.

    #execute the SQL statement to load the data
    con.execute(f"""
        CREATE OR REPLACE TABLE {table} AS
        SELECT *
        FROM read_csv(
            '{path.as_posix()}',
            header = true,
            sample_size = -1,
            store_rejects = true,
            rejects_table = 'reject_errors_{table}',
            rejects_scan = 'reject_scans_{table}'
        )
    """)
 
    loaded = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]                     #how many records were loaded
    rejected = con.execute(f"SELECT COUNT(*) FROM reject_errors_{table}").fetchone()[0]     #how many records were rejected
    ncols = len(con.execute(f"DESCRIBE {table}").fetchall())                                #number of columns from the table
    secs = time.perf_counter() - start                                                      #how long did it take
 
    #Load rejected record information into a permanent table that can be reviewed for errors
    con.execute(f"""
        INSERT INTO load_rejects
        SELECT '{table}', line, column_name, error_type, error_message
        FROM reject_errors_{table}
    """)

    #let us know what happened with the load
    print(f"{table:<14} {loaded:>12,} rows  {ncols:>4} cols  "
          f"{rejected:>8,} rejected  ({secs:,.1f}s)")
 
def main() -> None:

    #run the main code

    #set up the duckdb
    con = duckdb.connect(str(DB_PATH))
 
    #Create the load_rejects table to monitor failed loads
    con.execute("""
        CREATE OR REPLACE TABLE load_rejects (
            table_name VARCHAR, line BIGINT, column_name VARCHAR,
            error_type VARCHAR, error_message VARCHAR)
    """)

    # Audit tables, rebuilt on every run so they always describe the latest load
    #con.execute("""
    #    CREATE OR REPLACE TABLE load_log (
    #        table_name VARCHAR, source_file VARCHAR, rows_loaded BIGINT,
    #        rows_rejected BIGINT, n_columns INTEGER, seconds DOUBLE,
    #        loaded_at TIMESTAMP)
    #""")

    #con.execute(
    #    "INSERT INTO load_log VALUES (?, ?, ?, ?, ?, ?, current_timestamp)",
    #    [table, path.name, loaded, rejected, ncols, round(secs, 1)],
    #)

    #loop through our data sources and load the data
    for table, path in SOURCES.items():
        load_csv(con, table, path)
 
     #Create the scoped loan table
    con.execute("""
        CREATE OR REPLACE TABLE loans_scoped (
            id VARCHAR,
            issue_date datetime, 
            issue_qtr VARCHAR, 
            qtr_name VARCHAR, 
            bad_flag INT,
            fico_mid BIGINT, 
            int_rate FLOAT, 
            revol_util FLOAT,
            -- ORIGINATION (known at decision time): 
            funded_amnt FLOAT,
            loan_amnt FLOAT, 
            grade VARCHAR, 
            sub_grade VARCHAR, 
            fico_range_low BIGINT,
            fico_range_high BIGINT, 
            dti FLOAT, 
            annual_inc FLOAT, 
            emp_length VARCHAR, 
            home_ownership VARCHAR, 
            purpose VARCHAR, 
            addr_state VARCHAR, 
            inq_last_6mths FLOAT,
            -- OUTCOME (post-origination; not for model feature use): 
            loan_status VARCHAR, 
            total_pymnt FLOAT, 
            recoveries FLOAT, 
            last_pymnt_d VARCHAR,
            last_pymnt_d_date datetime)
    """)

    #insert this data into the scoped_loan table
    con.execute("""
        INSERT INTO loans_scoped(
        SELECT      id,
                    strptime(issue_d, '%b-%Y'),
                    date_trunc('quarter',strptime(issue_d, '%b-%Y')) as qtr,
                    strftime(strptime(issue_d, '%b-%Y'), '%Y-Q') || quarter(strptime(issue_d, '%b-%Y')) AS qtr_name,
                    CASE WHEN loan_status in('Default','Charged Off') THEN 1 ELSE 0 END as bad_flag,
                    (fico_range_low + fico_range_high) / 2 as FICO_AVG,
                    int_rate,
                    revol_util,
                    -- ORIGINATION (known at decision time): 
                    funded_amnt,
                    loan_amnt, 
                    grade, 
                    sub_grade, 
                    fico_range_low,
                    fico_range_high, 
                    dti, 
                    annual_inc, 
                    emp_length, 
                    home_ownership, 
                    purpose, 
                    addr_state, 
                    inq_last_6mths,
                    -- OUTCOME (post-origination; not for model feature use): 
                    loan_status, 
                    total_pymnt, 
                    recoveries, 
                    last_pymnt_d,
                    strptime(last_pymnt_d, '%b-%Y')
        FROM  raw_accepted
        WHERE strptime(issue_d, '%b-%Y') BETWEEN '2012-01-01' AND '2015-12-31'
                AND LOAN_STATUS in('Fully Paid','Charged Off','Default')
                AND trim(term) = '36 months'
        )
        
    """)

    #create the funnel_qtr table
    con.execute("""
            CREATE OR REPLACE TABLE funnel_qtr (
            qtr_start datetime, 
            qtr_end datetime, 
            qtr_name VARCHAR, 
            applications BIGINT,
            approvals BIGINT, 
            approval_rate FLOAT
                )
        """)

    #load data into the funnel_qtr table
    con.execute("""
        INSERT INTO funnel_qtr 
        (
            WITH quarter_dates AS 
                (
                SELECT 
                    -- 1. Name the date coming out of generate_series as 'issue_d_dt'
                    generate_series::DATE AS issue_d_dt,
                    
                    -- 2. Truncate it to the quarter start
                    date_trunc('quarter', generate_series)::DATE AS qtr_start,

                    -- 3. Add the last day of the quarter to make joins to the other data set easier
                    last_day(date_trunc('quarter', generate_series) + INTERVAL '2 months') AS qtr_end
                FROM 
                    generate_series(
                        '2012-01-01'::DATE, 
                        '2015-12-31'::DATE, 
                        INTERVAL '3 months'
                    )
                )

            SELECT 
                q.qtr_start, 
                q.qtr_end,
                strftime(q.qtr_start, '%Y-Q') || quarter(q.qtr_start) AS qtr_name,
                rej_cnt + app_cnt as applications,
                app_cnt as approvals,
                app_cnt / (rej_cnt + app_cnt) as approval_rate

            FROM 
                quarter_dates q
                LEFT JOIN (SELECT date_trunc('quarter', "Application Date") AS qtr, count('Amount Requested') as rej_cnt FROM RAW_REJECTED GROUP BY date_trunc('quarter', "Application Date")) R on R.qtr = q.qtr_start
                LEFT JOIN (SELECT date_trunc('quarter', strptime(issue_d, '%b-%Y')) as issue_qtr, count(id) as app_cnt FROM raw_accepted GROUP BY date_trunc('quarter', strptime(issue_d, '%b-%Y'))) A on A.issue_qtr = q.qtr_start
        )
        
    """)

    #print some data quality checks so the user can review for errors
    chck_val = []
    
    print(f"Int Rate Range: {con.execute('Select round(min(int_rate), 2) as val FROM loans_scoped').fetchone()[0]:.2f} | {con.execute('Select round(max(int_rate), 2) as val FROM loans_scoped').fetchone()[0]:.2f}")
    print(f"Date Range: {con.execute('Select min(issue_date) as val FROM loans_scoped').fetchone()[0]:%m/%d/%Y} | {con.execute('Select max(issue_date) as val FROM loans_scoped').fetchone()[0]:%m/%d/%Y}")
    print(f"Bad Loan Rate: {con.execute('Select avg(bad_flag) as val FROM loans_scoped').fetchone()[0]}")


    #check for null ID's
    chck_val.append(con.execute('Select count(*) as val FROM loans_scoped WHERE id IS NULL').fetchone()[0])
    print(f"Null ID: {chck_val[0]}")

    #check for null loan amounts
    chck_val.append(con.execute('Select count(*) as val FROM loans_scoped WHERE loan_amnt IS NULL').fetchone()[0])
    print(f"Null loan_amnt: {chck_val[1]}")

    #check for null grade values
    chck_val.append(con.execute('Select count(*) as val FROM loans_scoped WHERE grade IS NULL').fetchone()[0])
    print(f"Null grade: {chck_val[2]}")

    #check for null fico scores
    chck_val.append(con.execute('Select count(*) as val FROM loans_scoped WHERE fico_mid IS NULL').fetchone()[0])
    print(f"Null fico_mid: {chck_val[3]}")

    #check for null issue dates
    chck_val.append(con.execute('Select count(*) as val FROM loans_scoped WHERE issue_date IS NULL').fetchone()[0])
    print(f"Null issue_date: {chck_val[4]}")

    #check for duplicate ID values
    chck_val.append(con.execute('SELECT COUNT(id) - COUNT(DISTINCT id) FROM loans_scoped').fetchone()[0])
    print(f"Duplicate ids: {chck_val[5]}")

    #check for funded amounts that exceed loan amounts
    chck_val.append(con.execute('Select count(*) as val FROM loans_scoped WHERE funded_amnt > loan_amnt').fetchone()[0])
    print(f"Invalid fund_amt: {chck_val[6]}")

    #check for fico low range scores that exceed the high range score
    chck_val.append(con.execute('Select count(*) as val FROM loans_scoped WHERE fico_range_low > fico_range_high').fetchone()[0])
    print(f"Invalid FICO: {chck_val[7]}")

    #check for invalid interest rates
    chck_val.append(con.execute('Select count(*) as val FROM loans_scoped WHERE int_rate IS NULL or int_rate < 0 or int_rate > 50').fetchone()[0])
    print(f"Invalid Int Rate: {chck_val[8]}")

    #check for invalid FICO midpoint
    chck_val.append(con.execute('Select count(*) as val FROM loans_scoped WHERE fico_mid IS NULL or fico_mid < 300 or fico_mid > 850').fetchone()[0])
    print(f"Invalid FICO Midpoint: {chck_val[9]}")

    bad_rate = con.execute("SELECT AVG(bad_flag) FROM loans_scoped").fetchone()[0]
    chck_val.append(int(not 0.05 <= bad_rate <= 0.40))
    print(f"Bad rate out of range: {chck_val[10]}")
    
    #raise an error if something failed DQ checks
    if any(chck_val): raise ValueError("Data Quality Checks failed, please review logs")

    con.close()

if __name__ == "__main__":
    main()