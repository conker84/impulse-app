# Databricks notebook source
# MAGIC %md
# MAGIC <img src="../../docs/04_AnalyticalLayer.png" width="560" height="275">
# MAGIC
# MAGIC ### Analytical layer (silver) notebook for MDF time series processing.
# MAGIC * Reads bronze-level channel samples for the current run_id
# MAGIC * Collapses consecutive identical values into continuous time intervals per container/channel
# MAGIC * Appends results to the silver table (`channels`) and sets Delta properties for demo scale
# MAGIC * Expects widgets `catalog` and `schema`, and upstream task to set `next_run_id`
# MAGIC

# COMMAND ----------

# Imports
import sys
import pyspark.sql.functions as F
from pyspark.sql import Window

# COMMAND ----------

# DBTITLE 1,Add project root utils
sys.path.append("../")
from utils import schema_definitions

# COMMAND ----------

# MAGIC %md
# MAGIC ## Get context variables

# COMMAND ----------

# DBTITLE 1,Add Widgets
# Define Databricks widgets to parameterize catalog and schema

dbutils.widgets.text("catalog", "mda_demo")
dbutils.widgets.text("schema", "default")

# COMMAND ----------

# DBTITLE 1,Resolve runtime parameters
# Resolve widget values and derive fully-qualified table names

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
status_table_name = f"{catalog}.{schema}.status"
bronze_table = f"{catalog}.{schema}.bronze_channels"
samples_table = f"{catalog}.{schema}.channels"

print('Writing to:', samples_table)
print('bronze_table', bronze_table)

# COMMAND ----------

# DBTITLE 1,Read batch info
# Resolve current run_id and load the open files and relevant bronze/tag tables

current_run_id = dbutils.jobs.taskValues.get(taskKey = "get_next_batch", key = "next_run_id", debugValue = "NA")
open_files_raw = (spark.read.table(status_table_name)
              .where(F.col("run_id") == F.lit(current_run_id))
              .select("container_id", "filename")
              .collect()
              )
open_files = [r['filename'] for r in open_files_raw]
open_container_ids = [r['container_id'] for r in open_files_raw]
print('number of open files to convert:', len(open_files))

bronze_df = spark.read.table(bronze_table)

# filter to relevant data only
bronze_df = bronze_df.where(bronze_df.container_id.isin(open_container_ids))

# COMMAND ----------

# DBTITLE 1,Exit condition
# Short-circuit if there is no relevant bronze data for this run

# exit if empty
if bronze_df.isEmpty():
  dbutils.notebook.exit("Nothing to do.")


# COMMAND ----------

# DBTITLE 1,Window specs for run-length encoding
# Define window specs for per-channel ordering and cumulative grouping of changes

w = (Window
     .partitionBy(F.col("container_id"), F.col("channel_id"))
     .orderBy(F.col("time").asc())
     )

w2 = (Window
      .partitionBy(F.col("container_id"), F.col("channel_id"))
      .orderBy(F.col("time").asc())
      .rowsBetween(Window.unboundedPreceding, Window.currentRow)
      )

# COMMAND ----------

# DBTITLE 1,Apply run-length encoding
# Collapse consecutive equal values into [tstart, tend) intervals per container/channel

intervals_df = (bronze_df
                .withColumn("prev_value", F.lag(F.col("value")).over(w))
                .withColumn("next_time", F.coalesce(F.lead(F.col("time")).over(w), F.col("time")))
                .withColumn("value_diff", F.when(F.col("value") == F.col("prev_value"), F.lit(0)).otherwise(F.lit(1)))
                .withColumn("value_id", F.sum(F.col("value_diff")).over(w2))
                .groupBy(F.col("container_id"), F.col("channel_id"), F.col("value_id"))
                .agg(F.min(F.col("time")).alias("tstart"),
                    F.max(F.col("next_time")).alias("tend"),
                    F.first(F.col("value")).alias("value")
                    )
                .drop(F.col("value_id"))
                )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Out

# COMMAND ----------

# DBTITLE 1,Append Rows
# Append silver intervals clustered by container/channel (demo-friendly small files)

# Determine silver layer incrementally for current run_id
intervals_df.write.clusterBy('container_id', 'channel_id').mode('append').saveAsTable(samples_table)

# COMMAND ----------

# DBTITLE 1,Tune delta properties
# Tune Delta table target file size for demo performance (not for production)

#setting the target file size of the delta table to a small size (16MB) to speed up queries on the demo data
#in a real world setup, we would use a larger value
spark.sql(f"ALTER TABLE {samples_table} SET TBLPROPERTIES (delta.targetFileSize = '16777216')")

# COMMAND ----------


