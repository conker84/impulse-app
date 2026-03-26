# Databricks notebook source
# MAGIC %md
# MAGIC <img src="../../docs/05_StatusUpdate.png" width="560" height="275">
# MAGIC
# MAGIC ### Update files for succeeded conversions

# COMMAND ----------

# DBTITLE 1,Imports
import sys
from threading import Thread
from delta.tables import DeltaTable

sys.path.append("../")
from utils import utils

# COMMAND ----------

# DBTITLE 1,Resolve runtime parameters
# Configure parameters and derive identifiers
dbutils.widgets.text("catalog", "mda_demo")
dbutils.widgets.text("schema", "default")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
status_table_name = f"{catalog}.{schema}.status"
current_run_id = dbutils.jobs.taskValues.get(taskKey = "get_next_batch", key = "next_run_id", debugValue = "NA")

# COMMAND ----------

# DBTITLE 1,Mark run as succeeded
# Mark the current ingestion run as succeeded in the status table
utils.update_status(spark, status_table_name, current_run_id, 'succeeded')

# COMMAND ----------

# DBTITLE 1,Optimize
# Optimize and compact Delta tables for performance

tables = ['container_tags', 'container_metrics', 'channel_tags', 'channel_metrics', 'channels']

def run_optimize(table_name):
    DeltaTable.forName(spark, f'{catalog}.{schema}.{table_name}').optimize().executeCompaction()
    return

threads = [Thread(target=run_optimize, args=(t, )) for t in tables]
[t.start() for t in threads]
[t.join() for t in threads]
print("ALL DONE")

# COMMAND ----------


