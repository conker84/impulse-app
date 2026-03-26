# Databricks notebook source
# MAGIC %md
# MAGIC <img src="../../docs/03_ContainerMetadata.png" width="560" height="275">
# MAGIC
# MAGIC ### Derive and persist container-level tags and metrics for MDF files.
# MAGIC * Reads context (catalog/schema), identifies current batch files, and exits if none
# MAGIC * Creates tags (file metadata and parsed MDF comments) and writes to container_tags table
# MAGIC * Computes lightweight metrics (channel count, start/stop times, duration placeholder) and writes to container_metrics table

# COMMAND ----------

# DBTITLE 1,Imports
import datetime
import os
import sys
import re
import ast
import pyspark.sql.functions as F
import pyspark.sql.types as T
from asammdf import MDF
from delta.tables import DeltaTable

# COMMAND ----------

# DBTITLE 1,Add project root utils
sys.path.append("../")
from utils import schema_definitions
from utils import utils

# COMMAND ----------

# DBTITLE 1,Add widgets
# Define Databricks widgets to parameterize catalog and schema

dbutils.widgets.text("catalog", "mda_demo")
dbutils.widgets.text("schema", "default")

# COMMAND ----------

# DBTITLE 1,Resolve runtime parameters
# Read widget values, resolve fully qualified table names, and load the status table if it exists.
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
status_table_name = f"{catalog}.{schema}.status"
status_name_splitted = status_table_name.split('.')
if utils.table_exists(spark, status_name_splitted[0], status_name_splitted[1], status_name_splitted[2]):
  status_table_df = spark.read.table(status_table_name)

container_tags_table = f"{catalog}.{schema}.container_tags"
container_metrics_table = f"{catalog}.{schema}.container_metrics"

print('container_tags_table', container_tags_table)
print('container_metrics_table', container_metrics_table)

# COMMAND ----------

# DBTITLE 1,Gather current batch files
# Fetch current run_id from upstream task and collect open files and their container_ids from status table.
current_run_id = dbutils.jobs.taskValues.get(taskKey = "get_next_batch", key = "next_run_id", debugValue = "NA")
open_files_raw = (status_table_df
              .where(F.col("run_id") == F.lit(current_run_id))
              .select("container_id", "filename")
              .collect()
              )
open_files = [r['filename'] for r in open_files_raw]
open_container_ids = [r['container_id'] for r in open_files_raw]

print('number of open files to convert:', len(open_files))

# exit if empty
# Cell: Short-circuit when no files are scheduled in this run
if len(open_files) == 0:
  dbutils.notebook.exit("Nothing to do.")

# COMMAND ----------

# DBTITLE 1,Load target schemas
# Retrieve structured schemas for tags and metrics (Spark StructTypes).
tags_schema = schema_definitions.get_mdf4_schemas()['tags_schema']
metrics_schema = schema_definitions.get_mdf4_schemas()['metrics_schema']

# COMMAND ----------

# DBTITLE 1,Parse MDF comment helper
# Read the MDF file comment and extract business fields embedded as XML-like <TX> content.
# Returns a tuple: (brand, model, vehicle_key, from_city, to_city, condition, experiment_id)
# Documentation:
# - Purpose: Extract domain metadata from the MDF file's comment field for tagging.
# - Inputs: `file_path` to the MDF file.
# - Outputs: Tuple of seven strings: (brand, model, vehicle_key, from_city, to_city, condition, experiment_id).
# - Failure modes: If comment is missing/malformed or keys are absent, defaults to 'NA' values.
# - Performance: Opens the MDF to access header info; lightweight relative to full data reads.
def parse_mdf_comment(file_path: str) -> tuple:
    mdf = MDF(file_path)
    pattern = r"<TX>(.*?)</TX>"
    matches = re.findall(pattern, mdf.info()['comment'])
    brand, model, vehicle_key, from_city, to_city, condition, experiment_id = 'NA', 'NA', 'NA', 'NA', 'NA', 'NA', 'NA'
    if matches:
        matches_dict = ast.literal_eval(matches[0])
        brand = matches_dict.get('brand', 'NA')
        model = matches_dict.get('model', 'NA')
        vehicle_key = matches_dict.get('vehicle_key', 'NA')
        from_city = matches_dict.get('from_city', 'NA')
        to_city = matches_dict.get('to_city', 'NA')
        condition = matches_dict.get('condition', 'NA')
        experiment_id = matches_dict.get('experiment_id', 'NA')
    return (brand, model, vehicle_key, from_city, to_city, condition, experiment_id)
  
# Map container_id to parsed MDF comment fields for later tag/metric enrichment.
# Documentation:
# - Purpose: Precompute per-container parsed comment fields to avoid repeated file header reads.
# - Inputs: `open_files` and `open_container_ids` from the current run.
# - Outputs: Dict `mdf_comments`: {container_id: (brand, model, vehicle_key, from_city, to_city, condition, experiment_id)}.
mdf_comments = {cid: parse_mdf_comment(fn) for fn, cid in zip(open_files, open_container_ids)}

# COMMAND ----------

# DBTITLE 1,Build and persist container tags
# Derive default tags (URIs, filename, size) and domain tags from MDF comments; write to container_tags table.
tags = [{'container_id': cid, 'key': 'file_uri', 'value': fn} for fn, cid in zip(open_files, open_container_ids)]
tags.extend([{'container_id': cid, 'key': 'base_uri', 'value': os.path.dirname(fn)} for fn, cid in zip(open_files, open_container_ids)])
tags.extend([{'container_id': cid, 'key': 'filename', 'value': os.path.basename(fn)} for fn, cid in zip(open_files, open_container_ids)])
tags.extend([{'container_id': cid, 'key': 'filesize_mb', 'value': os.path.getsize(fn) / 1024 / 1024} for fn, cid in zip(open_files, open_container_ids)])
tags.extend([{'container_id': cid, 'key': 'brand', 'value': mdf_comments[cid][0]} for cid in open_container_ids])
tags.extend([{'container_id': cid, 'key': 'model', 'value': mdf_comments[cid][1]} for cid in open_container_ids])
tags.extend([{'container_id': cid, 'key': 'vehicle_key', 'value': mdf_comments[cid][2]} for cid in open_container_ids])
tags.extend([{'container_id': cid, 'key': 'from_city', 'value': mdf_comments[cid][3]} for cid in open_container_ids])
tags.extend([{'container_id': cid, 'key': 'to_city', 'value': mdf_comments[cid][4]} for cid in open_container_ids])
tags.extend([{'container_id': cid, 'key': 'condition', 'value': mdf_comments[cid][5]} for cid in open_container_ids])
tags.extend([{'container_id': cid, 'key': 'experiment_id', 'value': mdf_comments[cid][6]} for cid in open_container_ids])
tagsdf = spark.createDataFrame(tags)

# COMMAND ----------

# Write tags to Delta table
# Append tag records, clustered by container_id, to the target table.
# Documentation:
# - Purpose: Persist tag rows into the `container_tags` Delta table.
# - Inputs: DataFrame `tagsdf`.
# - Outputs: Appended rows in table `container_tags_table`.
# - Side effects: Table write with bucketing/cluster by `container_id` for layout optimization.
# - Assumptions: Idempotency not guaranteed; a future MERGE is recommended for deduplication.
if not spark.catalog.tableExists(container_tags_table):
    (tagsdf.write
      .clusterBy('container_id')
      .format("delta")
      .mode("append")
      .saveAsTable(container_tags_table))
else:
  t_container_tags_table = DeltaTable.forName(spark, container_tags_table)
  (t_container_tags_table.alias("tags")
    .merge(tagsdf.alias("new_tags"),  "tags.container_id = new_tags.container_id and tags.key = new_tags.key")
      .whenMatchedUpdateAll()
      .whenNotMatchedInsertAll()
      .execute()
  )


# COMMAND ----------

# MAGIC %md
# MAGIC ## Create Metrics

# COMMAND ----------

# DBTITLE 1,Compute container-level metrics
# Distribute open files across partitions, read MDF headers to extract metrics, and build a metrics DataFrame.
file2cid = {fn: cid for fn, cid in zip(open_files, open_container_ids)}

def extract(it):
  for _, filename in it:
    mdf = MDF(filename)
    now_dt = datetime.datetime.now()
    r = {
      'container_id': file2cid[filename],
      'vehicle_key': mdf_comments[file2cid[filename]][2],
      'num_channels': len(mdf.channels_db),
      'start_dt': mdf.header.start_time,
      'stop_dt': now_dt,
      'start_ts': int(mdf.header.start_time.timestamp() * 1000),
      'stop_ts': int(now_dt.timestamp() * 1000),
      'duration_ms': 0
    }
    mdf.close()
    yield r

# Deterministic partitioner to co-locate file work per partition.
open_files_map = {f: i for i,f in enumerate(open_files)}

def partitioner(key, *args, **kwargs):
  return open_files_map[key]

# load open files
num_partitions = len(open_files)
metrics_rdd = spark.sparkContext.parallelize(open_files)
# distribute to partitions
metrics_rdd = metrics_rdd.map(lambda x: (x, x))
metrics_rdd = metrics_rdd.partitionBy(num_partitions, partitionFunc=partitioner)
metrics_rdd = metrics_rdd.mapPartitions(extract, preservesPartitioning=True)

metricsdf = metrics_rdd.toDF(schema=metrics_schema)


# COMMAND ----------

# Write metrics to Delta table
# Append metrics, clustered by container_id, to the container_metrics table.
# Documentation:
# - Purpose: Persist computed metrics into the `container_metrics` Delta table.
# - Inputs: DataFrame `metricsdf`.
# - Outputs: Appended rows in table `container_metrics_table`.
# - Side effects: Table write with bucketing/cluster by `container_id`.
# - Assumptions: Idempotency not guaranteed; a future MERGE is recommended for deduplication.
if not spark.catalog.tableExists(container_metrics_table):
  (metricsdf.write
    .clusterBy('container_id')
    .format("delta")
    .mode("append")
    .saveAsTable(container_metrics_table))
else:
  t_container_tags_table = DeltaTable.forName(spark, container_metrics_table)
  (t_container_tags_table.alias("m")
    .merge(metricsdf.alias("nm"),  "m.container_id = nm.container_id")
      .whenMatchedUpdateAll()
      .whenNotMatchedInsertAll()
      .execute()
  )
