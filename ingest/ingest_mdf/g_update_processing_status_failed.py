# Databricks notebook source
# MAGIC %md
# MAGIC <img src="../../docs/05_StatusUpdate.png" width="560" height="275">
# MAGIC
# MAGIC ### Update workflow run status to 'failed' in the status table.
# MAGIC * Trigger: This notebook is configured as an on-failure step in the ingestion workflow.
# MAGIC * Environment: Runs in Databricks and relies on 'dbutils' and an active 'spark' session.

# COMMAND ----------

# DBTITLE 1,Imports
import delta
import pyspark.sql.functions as F
import sys, traceback

# COMMAND ----------

# DBTITLE 1,Add project root utils
sys.path.append("../")
from utils import utils

# COMMAND ----------

# DBTITLE 1,Define Widgets
# Define job parameters for catalog and schema. Defaults support local/dev runs.
dbutils.widgets.text("catalog", "mda_demo")
dbutils.widgets.text("schema", "default")

# COMMAND ----------

# DBTITLE 1,Resolve runtime parameters
# Read widget values, build the fully qualified status table name, and retrieve the current run id from a previous task.
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
status_table_name = f"{catalog}.{schema}.status"
container_tags_table = f"{catalog}.{schema}.container_tags"
container_metrics_table = f"{catalog}.{schema}.container_metrics"
bronze_table = f"{catalog}.{schema}.bronze_channels"
samples_table = f"{catalog}.{schema}.channels"
channel_tags_table = f"{catalog}.{schema}.channel_tags"
channel_metrics_table = f"{catalog}.{schema}.channel_metrics"

current_run_id = dbutils.jobs.taskValues.get(taskKey = "get_next_batch", key = "next_run_id", debugValue = "NA")
status_table_df = None
status_name_splitted = status_table_name.split('.')
if utils.table_exists(spark, status_name_splitted[0], status_name_splitted[1], status_name_splitted[2]):
  status_table_df = spark.read.table(status_table_name)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Execute Rollback

# COMMAND ----------

# DBTITLE 1,Find containers to rollback
# get all containers in failed run
open_files_raw = (status_table_df
                  .where(F.col("run_id") == F.lit(current_run_id))
                  .select("container_id")
                  .collect()
                  )
open_container_ids = [r['container_id'] for r in open_files_raw]
open_container_ids

# COMMAND ----------

# DBTITLE 1,Rollback samples
try:
  dt = delta.DeltaTable.forName(spark, samples_table)
  dt.delete(F.col("container_id").isin(open_container_ids))
  print("OK")
except:
  exc_type, exc_value, exc_traceback = sys.exc_info()
  traceback.print_exception(exc_type, exc_value, exc_traceback)

# COMMAND ----------

# DBTITLE 1,Rollback Channel Tags
try:
  dt = delta.DeltaTable.forName(spark, channel_tags_table)
  dt.delete(F.col("container_id").isin(open_container_ids))
  print("OK")
except:
  exc_type, exc_value, exc_traceback = sys.exc_info()
  traceback.print_exception(exc_type, exc_value, exc_traceback)

# COMMAND ----------

# DBTITLE 1,Rollback Channel Metrics
try:
  dt = delta.DeltaTable.forName(spark, channel_metrics_table)
  dt.delete(F.col("container_id").isin(open_container_ids))
  print("OK")
except:
  exc_type, exc_value, exc_traceback = sys.exc_info()
  traceback.print_exception(exc_type, exc_value, exc_traceback)

# COMMAND ----------

# DBTITLE 1,Rollback Container Tags
try:
  dt = delta.DeltaTable.forName(spark, container_tags_table)
  dt.delete(F.col("container_id").isin(open_container_ids))
  print("OK")
except:
  exc_type, exc_value, exc_traceback = sys.exc_info()
  traceback.print_exception(exc_type, exc_value, exc_traceback)

# COMMAND ----------

# DBTITLE 1,Rollback Container Metrics
try:
  dt = delta.DeltaTable.forName(spark, container_metrics_table)
  dt.delete(F.col("container_id").isin(open_container_ids))
  print("OK")
except:
  exc_type, exc_value, exc_traceback = sys.exc_info()
  traceback.print_exception(exc_type, exc_value, exc_traceback)

# COMMAND ----------

# DBTITLE 1,Rollback Bronze Data
try:
  dt = delta.DeltaTable.forName(spark, bronze_table)
  dt.delete(F.col("container_id").isin(open_container_ids))
  print("OK")
except:
  exc_type, exc_value, exc_traceback = sys.exc_info()
  traceback.print_exception(exc_type, exc_value, exc_traceback)

# COMMAND ----------

# DBTITLE 1,Mark as failed
# Update the centralized status table to reflect a failed workflow run for observability and retries.
utils.update_status(spark, status_table_name, current_run_id, 'failed')

# COMMAND ----------


