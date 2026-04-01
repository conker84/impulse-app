# Databricks notebook source
# MAGIC %md 
# MAGIC <img src="../../docs/02_BatchDefinition.png" width="560" height="275">
# MAGIC
# MAGIC ### Detect any new files that need to be processed
# MAGIC
# MAGIC * Checks `mf4_volume` directory for new files
# MAGIC * Creates entries in the `stats` table to track status of mdf files
# MAGIC
# MAGIC  Purpose: Determine the next run_id to process for MDF ingest and mark it
# MAGIC as 'in_progress' in the status table. Intended to be run as part
# MAGIC of a Databricks Jobs workflow.
# MAGIC Environment: Requires Databricks runtime with 'spark' and 'dbutils'.
# MAGIC Inputs (widgets):
# MAGIC   - catalog: Unity Catalog catalog name
# MAGIC   - schema: Unity Catalog schema name
# MAGIC   - max_batch_size: not used in this notebook, kept for interface parity
# MAGIC   - reprocess_current_run: whether to re-run an active 'in_progress' run
# MAGIC   - reprocess_last_failed_run: whether to re-run the most recent failed run
# MAGIC Side effects:
# MAGIC   - Updates table `<catalog>.<schema>.status`
# MAGIC   - Emits task value 'next_run_id' for downstream tasks

# COMMAND ----------

# DBTITLE 1,Imports
import pyspark.sql.functions as F
from datetime import datetime
import sys

# COMMAND ----------

# Make project utilities importable when running as a notebook or job
sys.path.append("../")
from utils import utils

# COMMAND ----------

# DBTITLE 1,Define widgets
# Define runtime parameters (override in Job tasks or at execution time)
dbutils.widgets.text("catalog", "mda_demo")
dbutils.widgets.text("schema", "default")
dbutils.widgets.text("max_batch_size", "100")
# Whether to re-execute an already active run and/or the latest failed run
# Note: values are strings; evaluated case-insensitively to booleans below
dbutils.widgets.dropdown("reprocess_current_run", "True", ["True", "False"])
dbutils.widgets.dropdown("reprocess_last_failed_run", "True", ["True", "False"])

# COMMAND ----------

# DBTITLE 1,Resolve runtime parameters
# Resolve table location and validate presence of the status table
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
status_table_name = f"{catalog}.{schema}.status"
status_name_splitted = status_table_name.split('.')
if utils.table_exists(spark, status_name_splitted[0], status_name_splitted[1], status_name_splitted[2]):
  status_table_df = spark.read.table(status_table_name)
else:
  raise Exception("status table not found. Aborting")

# Coerce widget strings to booleans for control flow
reprocess_current_run = dbutils.widgets.get("reprocess_current_run").lower() == 'true'
reprocess_last_failed_run = dbutils.widgets.get("reprocess_last_failed_run").lower() == 'true'

# COMMAND ----------

# DBTITLE 1,Resolve which batch to run
# Initialize selection variables and capture a log-friendly timestamp
next_load_ts = ""
next_run_id = "noop"
logging_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Compute status-derived views and counts
current_runs_df = utils.get_files_by_status(status_table_df, 'in_progress')
current_failures_df = utils.get_files_by_status(status_table_df, 'failed')
current_unprocessed_df = utils.get_files_by_status(status_table_df, 'unprocessed')
current_runs_count = current_runs_df.select("run_id").distinct().count()
current_failure_count = current_failures_df.select("run_id").distinct().count()
current_unprocessed_count = current_unprocessed_df.select("run_id").distinct().count()
print(f"active runs: {current_runs_count}, failed runs: {current_failure_count}, unprocessed runs: {current_unprocessed_count}")

# Selection logic priority:
# 1) At most one active run is allowed. If one exists, optionally reprocess it.
# 2) Else, optionally reprocess the most recent failed run.
# 3) Else, take the earliest unprocessed run by _load_ts.
# 4) If none of the above apply, next_run_id remains 'noop'.
# checking for active runs in the status table
if current_runs_count > 1:
  # Defensive guard: multiple active runs indicates status table inconsistency
  raise Exception(f"""
                  [{logging_time}] It is not allowed to have more than 1 active run (status 'in_progress').
                  Please fix the status table. Exiting.
                  """)
elif current_runs_count == 1:
  if reprocess_current_run:
    # Re-run the single active run
    next_run_id = current_runs_df.collect()[0]['run_id']
    print(f"[{logging_time}] Reprocessing last active run: {next_run_id}")
  else:
    raise Exception(f"""
                    [{logging_time}] There is already an active run in the status table.
                    If this run should be reprocessed, please set parameter 'reprocess_current_run' to 'True'
                    """)

# checking for failed runs in the status table
elif current_failure_count > 0:
  if reprocess_last_failed_run:
    # Select the latest failed run by descending load timestamp
    current_row = current_failures_df.orderBy(F.col("_load_ts").desc()).collect()[0]
    next_run_id = current_row['run_id']
    print(f"[{logging_time}] Reprocessing last failed run: {next_run_id}")
  else:
    print(f"""
          [{logging_time}] Warning: Found {current_failure_count} failed runs in the status table.
          If failed runs should be reprocessed, please set parameter 'reprocess_last_failed_run' to 'True'
                  """)

# no active runs and no failed runs to be reprocessed. Continue with the next available run_id
elif current_unprocessed_count > 0:
  # Choose the earliest unprocessed run by ascending load timestamp
  current_row = current_unprocessed_df
  current_row = current_row.orderBy(F.col("_load_ts").asc())
  current_row = current_row.collect()[0]
  next_run_id = current_row['run_id']

print(f"run_id: {next_run_id}")

# Short-circuit when there is nothing to process
if next_run_id == "noop":
  dbutils.jobs.taskValues.set(key = "next_run_id", value = next_run_id)
  dbutils.notebook.exit("Nothing to process.")

# COMMAND ----------

# DBTITLE 1,Update status
# Persist selection by marking chosen run_id as 'in_progress'
utils.update_status(spark, status_table_name, next_run_id, 'in_progress')

# Sanity check: exactly one active run must exist after the update
assert (status_table_df
        .where(F.col("status") == F.lit("in_progress"))
        .select(F.col("run_id"))
        .distinct()
        .count() == 1)

# COMMAND ----------

# DBTITLE 1,Expose next_run_id
# Expose the selected run_id to downstream tasks in the job
dbutils.jobs.taskValues.set(key = "next_run_id", value = next_run_id)

# COMMAND ----------


