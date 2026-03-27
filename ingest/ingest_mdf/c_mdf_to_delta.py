# Databricks notebook source
# MAGIC %md
# MAGIC <img src="../../docs/03_MDFtoDelta.png" width="560" height="275">
# MAGIC
# MAGIC ### Convert open files from MDF to delta
# MAGIC * Detect run context and selected files from the status table
# MAGIC * Extract channel metadata from MDF files
# MAGIC * Balance work across bins for parallelism
# MAGIC * Read numeric timeseries while honoring invalidation bits and metadata
# MAGIC * Write Bronze timeseries to Delta clustered by container and channel

# COMMAND ----------

# DBTITLE 1,Imports
import sys
import ast
import pandas as pd
import numpy as np
import pyspark.sql.functions as F
import pyspark.sql.types as T
from itertools import chain
from pyspark.sql import Window
from pyspark.sql.types import ArrayType, IntegerType
from pyspark.sql.functions import pandas_udf

from asammdf import MDF
import binpacking

# COMMAND ----------

# DBTITLE 1,Add project root utils
sys.path.append("../")
from utils import schema_definitions
from utils import utils

# COMMAND ----------

# COMMAND ----------

# MAGIC %md
# MAGIC ## Get context variables

# COMMAND ----------

# DBTITLE 1,Read Widgets
# Define Databricks widgets used to parameterize catalog/schema and bin size
dbutils.widgets.text("catalog", "mda_demo")
dbutils.widgets.text("schema", "default")
dbutils.widgets.text("max_datapoints_per_bin", "1000000")

# COMMAND ----------

# DBTITLE 1,Resolve runtime parameters
# Resolve parameters, compute table names, and load status table if present
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
status_table_name = f"{catalog}.{schema}.status"
status_table_df = None
status_name_splitted = status_table_name.split('.')
if utils.table_exists(spark, status_name_splitted[0], status_name_splitted[1], status_name_splitted[2]):
  status_table_df = spark.read.table(status_table_name)

bronze_table = f"{catalog}.{schema}.bronze_channels"

max_datapoints_per_bin = int(dbutils.widgets.get("max_datapoints_per_bin"))

print('Writing to:', bronze_table)

# COMMAND ----------

# DBTITLE 1,Load batch info
# Determine the current batch run identifier and gather files to process
current_run_id = dbutils.jobs.taskValues.get(taskKey = "get_next_batch", key = "next_run_id", debugValue = "NA")
print('current_run_id:', current_run_id)
open_files_raw = (status_table_df
              .where(F.col("run_id") == F.lit(current_run_id))
              .select("container_id", "filename")
              .collect()
              )
open_files = [r['filename'] for r in open_files_raw]
open_container_ids = [r['container_id'] for r in open_files_raw]

file2cid = {fn: cid for fn, cid in zip(open_files, open_container_ids)}
file2cid_map = F.create_map([F.lit(x) for x in chain(*file2cid.items())])

print('first file', open_files[0])
print('number of open files to convert:', len(open_files))

# COMMAND ----------

# DBTITLE 1,Exit when empty
# Guard: If no open files found for this run, exit early to skip downstream work
if len(open_files) == 0:
  dbutils.notebook.exit("Nothing to do.")

# COMMAND ----------

# Target schema for Bronze timeseries rows produced by MDF conversion
schema = schema_definitions.get_mdf4_schemas()['bronze_schema']

# COMMAND ----------

# MAGIC %md
# MAGIC ## Conversion functions

# COMMAND ----------

# Helper functions: channel discovery and bin packing

@pandas_udf(ArrayType(ArrayType(IntegerType())))
def get_channel_indices(filenames: pd.Series) -> pd.Series:
  result = []
  for filename in filenames:
    channel_ids = []
    mdf = MDF(filename)
    for index in mdf.virtual_groups:
      samples_count = mdf.virtual_groups[index].cycles_nr
      if samples_count <= 1:
        continue
      tmp_channel_ids = [
        (gp_index, ch_index, samples_count)
        for gp_index, channel_indexes in mdf.included_channels(index)[index].items()
        for ch_index in channel_indexes
      ]
      channel_ids.extend(tmp_channel_ids)
    result.append(channel_ids)
    mdf.close()
  return pd.Series(result)

# Reader over bins: opens each MDF once per file and reads numeric samples with metadata
# Uses applyInPandas interface (receives/returns pandas DataFrame) for serverless compatibility

def read_mdf_bin(pdf):
  pdf = pdf.sort_values("filename")
  rows = []
  prev_filename = ''
  mdf = None
  for _, r in pdf.iterrows():
    filename, channel_id = r["filename"], int(r["channel_id"])
    group_idx, channel_idx = int(r["group_idx"]), int(r["channel_idx"])
    if prev_filename != filename:
        if mdf is not None:
            mdf.close()
        mdf = MDF(filename)
        prev_filename = filename
    channel = mdf.select([(None, group_idx, channel_idx)], copy_master=True, raw=False)[0]
    times = np.array(channel.timestamps, dtype=np.int64)
    values = channel.samples
    # we only consider numeric timeseries
    if not np.issubdtype(type(values[0]), np.number):
        continue
    # handle invalidation bits
    invalid = channel.invalidation_bits
    if invalid is not None:
        invalid_idx = np.argwhere(invalid)
        if len(invalid_idx) > 0:
            values[invalid_idx] = np.nan
    brand = model = vehicle_key = from_city = to_city = condition = experiment_id = 'NA'
    if channel.comment is not None:
        comment_dict = ast.literal_eval(channel.comment)
        brand = str(comment_dict.get('brand', 'NA'))
        model = str(comment_dict.get('model', 'NA'))
        vehicle_key = str(comment_dict.get('vehicle_key', 'NA'))
        from_city = str(comment_dict.get('from_city', 'NA'))
        to_city = str(comment_dict.get('to_city', 'NA'))
        condition = str(comment_dict.get('condition', 'NA'))
        experiment_id = str(comment_dict.get('experiment_id', 'NA'))
    for i in range(len(times)):
      rows.append((filename, channel_id, group_idx, channel_idx, channel.name, channel.unit, int(times[i]), float(values[i]),
             brand, model, vehicle_key, from_city, to_city, condition, experiment_id))
  if mdf is not None:
      mdf.close()
  columns = ["filename", "channel_id", "group_idx", "channel_idx", "channel_name", "unit",
             "time", "value", "brand", "model", "vehicle_key", "from_city", "to_city",
             "condition", "experiment_id"]
  return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)


# COMMAND ----------

# MAGIC %md
# MAGIC ## Convert

# COMMAND ----------

# DBTITLE 1,Prepare batch
# Build per-file, per-channel plan with sample counts for bin packing

df = (spark
      .createDataFrame([(x,) for x in open_files], "filename string")
      .withColumn("channel_indices", get_channel_indices(F.col("filename")))
      .where(F.array_size(F.col("channel_indices")) > 0)
      .withColumn("idx", F.explode("channel_indices"))
      .withColumn("group_idx", F.col("idx").getItem(0))
      .withColumn("channel_idx", F.col("idx").getItem(1))
      .withColumn("sample_count", F.col("idx").getItem(2))
      .withColumn("channel_id", F.row_number().over(Window.partitionBy('filename').orderBy('group_idx', 'channel_idx')))
      .select("filename", "channel_id", "group_idx", "channel_idx", "sample_count")
      )

# COMMAND ----------

# DBTITLE 1,Sort by filename and group_idx
# Materialize and deterministically sort channel rows prior to sizing bins
all_rows = sorted(df.collect(), key=lambda r: (r['filename'], r['group_idx']))

# COMMAND ----------

# DBTITLE 1,Estimate bin parameters
print(f"max_datapoints_per_bin: {max_datapoints_per_bin}")

# COMMAND ----------

# DBTITLE 1,Run binpacking
# Perform global bin packing of (file, channel) tasks to balance sample counts per partition
# Produces bins with approximately max_datapoints_per_bin samples for parallel processing
#Performing global binpacking 
all_ids = [(r["filename"], r["channel_id"], r["group_idx"], r["channel_idx"], r["sample_count"]) for r in all_rows]
bins = binpacking.to_constant_volume(all_ids, max_datapoints_per_bin, weight_pos=4)
bins_flattened = [(x[0], x[1], x[2], x[3], x[4], bin_index) for bin_index in range(0,len(bins)) for x in bins[bin_index]]
assert len(bins_flattened) == len(all_ids)

# COMMAND ----------

# DBTITLE 1,Prepare task DataFrame
# Define intermediate Spark schema for the bin plan rows
schema_str = "filename string, channel_id int, group_idx int, channel_idx int, sample_count int, bin_idx int"
df = spark.createDataFrame(bins_flattened, schema_str).repartition(len(bins))

# COMMAND ----------

# DBTITLE 1,Read mdf file into DataFrame
# Execute the read via applyInPandas grouped by bin_idx, then attach container id
resdf_raw = (df
             .groupBy("bin_idx")
             .applyInPandas(read_mdf_bin, schema=schema)
             .withColumn("container_id", file2cid_map[F.col('filename')].cast('bigint'))
             .select("container_id", "channel_id", "time", "value", "filename", "group_idx", "channel_idx", "channel_name", "unit",
                     "brand", "model", "from_city", "to_city", "condition", "experiment_id")
             )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Out

# COMMAND ----------

# DBTITLE 1,Append rows
# Persist Bronze timeseries clustered by container and channel for efficient reads
resdf_raw.write.clusterBy('container_id', 'channel_id').mode('append').saveAsTable(bronze_table)
