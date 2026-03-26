# Databricks notebook source
# MAGIC %md
# MAGIC ![image](../../docs/flow.png)
# MAGIC
# MAGIC ### Generate channel-level tags and metrics from `bronze_channels` and write results to Delta tables.
# MAGIC

# COMMAND ----------

# Imports
import pyspark.sql.functions as F
from delta.tables import DeltaTable

# COMMAND ----------
sys.path.append("../")
from utils import schema_definitions
from utils import utils


# COMMAND ----------

# Define Databricks widgets for catalog and schema with sensible defaults

dbutils.widgets.text("catalog", "mda_demo")
dbutils.widgets.text("schema", "default")

# COMMAND ----------

# Resolve widget values and construct fully qualified table names

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
status_table_name = f"{catalog}.{schema}.status"
status_name_splitted = status_table_name.split('.')
if utils.table_exists(spark, status_name_splitted[0], status_name_splitted[1], status_name_splitted[2]):
  status_table_df = spark.read.table(status_table_name)

channel_tags_table = f"{catalog}.{schema}.channel_tags"
channel_metrics_table = f"{catalog}.{schema}.channel_metrics"
bronze_table = f"{catalog}.{schema}.bronze_channels"

print('channel_tags_table', channel_tags_table)
print('channel_metrics_table', channel_metrics_table)

# Gather current batch files
# Fetch current run_id from upstream task and collect open files and their container_ids from status table.
# Documentation:
# - Purpose: Determine which MDF files are scheduled for processing in the current run.
# - Inputs:
#   - Job task value: key="next_run_id" set by the upstream task `get_next_batch`.
#   - DataFrame: `status_table_df` with columns `run_id`, `container_id`, `filename`.
# - Outputs:
#   - Lists: `open_files` (file paths), `open_container_ids` (corresponding container IDs).
# - Side effects: Exits notebook early if no files are scheduled.
# - Assumptions: Upstream job populated `next_run_id` and status table rows for this run.
current_run_id = dbutils.jobs.taskValues.get(taskKey = "get_next_batch", key = "next_run_id", debugValue = "NA")
open_files_raw = (status_table_df
              .where(F.col("run_id") == F.lit(current_run_id))
              .select("container_id", "filename")
              .collect()
              )
open_files = [r['filename'] for r in open_files_raw]
open_container_ids = [r['container_id'] for r in open_files_raw]

print('number of open files to convert:', len(open_files))

# COMMAND ----------

# Read channel samples from the bronze layer

samples_df = (spark.read
              .table(bronze_table)
              .where(F.col("container_id").isin(open_container_ids)))


# COMMAND ----------

# Compute per-channel metrics (counts, min/max/mean, time bounds, duration, sample rate, type)

channel_metrics_df = (samples_df
                      .groupBy(F.col("container_id"),
                               F.col("channel_id")
                               )
                      .agg(F.count(F.col("channel_id")).cast('int').alias("sample_count"),
                           F.min(F.col("value")).alias("min"),
                           F.max(F.col("value")).alias("max"),
                           F.avg(F.col("value")).alias("mean"),
                           F.min(F.col("time")).alias("begin_ms"),
                           F.max(F.col("time")).alias("end_ms"),
                           )
                      .withColumn("duration_ms", (F.col("end_ms") - F.col("begin_ms")))
                      .withColumn("sample_rate", F.col("sample_count")/(F.col("duration_ms")/1000./1000.))
                      .withColumn("value_type", F.lit("DOUBLE"))
                      )

# COMMAND ----------

# Define channel tag columns to aggregate and create aggregation expressions

channel_tags = ['group_idx', 'channel_idx', 'channel_name', 'unit', "brand", "model",
                "from_city", "to_city", "condition", "experiment_id"]
agg_expressions = []
for tag in channel_tags:
    tmp_expr = F.first(F.col(tag).cast("string")).alias(tag)
    agg_expressions.append(tmp_expr)

# COMMAND ----------

# Aggregate tag columns per channel and unpivot to key/value representation

channel_tags_df = (samples_df
                   .groupBy(F.col('container_id'), F.col("channel_id"))
                   .agg(*agg_expressions)
                   .unpivot(["container_id","channel_id"], channel_tags, "key", "value")
                   )

# COMMAND ----------

# Write results to Delta tables clustered by container and channel

#ToDo: Determine channel metrics and tags incrementally
# channel_metrics upsert (create table if missing, else MERGE on container_id, channel_id)
if not spark.catalog.tableExists(channel_metrics_table):
    (channel_metrics_df.write
      .clusterBy('container_id', 'channel_id')
      .format("delta")
      .mode("append")
      .saveAsTable(channel_metrics_table))
else:
  t_channel_metrics = DeltaTable.forName(spark, channel_metrics_table)
  (t_channel_metrics.alias("m")
    .merge(channel_metrics_df.alias("nm"),  "m.container_id = nm.container_id and m.channel_id = nm.channel_id")
      .whenMatchedUpdateAll()
      .whenNotMatchedInsertAll()
      .execute()
  )

# channel_tags upsert (create table if missing, else MERGE on container_id, channel_id, key)
if not spark.catalog.tableExists(channel_tags_table):
    (channel_tags_df.write
      .clusterBy('container_id', 'channel_id')
      .format("delta")
      .mode("append")
      .saveAsTable(channel_tags_table))
else:
  t_channel_tags = DeltaTable.forName(spark, channel_tags_table)
  (t_channel_tags.alias("tags")
    .merge(channel_tags_df.alias("new_tags"),  "tags.container_id = new_tags.container_id and tags.channel_id = new_tags.channel_id and tags.key = new_tags.key")
      .whenMatchedUpdateAll()
      .whenNotMatchedInsertAll()
      .execute()
  )
