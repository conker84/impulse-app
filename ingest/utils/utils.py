"""
Utility functions for the time series ingest solution accelerator.

This module provides helpers for:
- Checking existence of catalogs, schemas, and tables in Spark/Unity Catalog
- Data compaction helpers (e.g., converting dense time series to sparse)
- Timestamp conversions between datetime and microseconds
- Working with Delta Lake tables for status updates and upserts
- Lightweight file utilities (zip extraction, string parsing)
- Converting OBD CSV datasets into MDF (ASAM MDF v4) files for simulation/demo data
"""

import os
import re
import zipfile
import glob
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple
import pyspark.sql.functions as F
from pyspark.sql import DataFrame
from functools import reduce
from delta.tables import DeltaTable


def get_files_by_status(status_table_df: DataFrame, status: str):
    """Filter a status table DataFrame by a specific status value.

    Args:
        status_table_df (pyspark.sql.DataFrame): DataFrame with a ``status`` column.
        status (str): Status value to filter for.

    Returns:
        pyspark.sql.DataFrame: Filtered DataFrame where ``status == status``.
    """
    result_df = status_table_df.where(F.col("status") == F.lit(status))
    return result_df


def update_status(spark, status_table_name: str, run_id: str, new_status: str):
    """Update the ``status`` column for rows with a specific ``run_id``.

    The update is performed via an upsert/merge into the Delta table.

    Args:
        spark (pyspark.sql.SparkSession): Active Spark session.
        status_table_name (str): Fully qualified Delta table name to update.
        run_id (str): Run identifier to match rows.
        new_status (str): New status value to set.
    """
    updates_df = (
        spark
        .read
        .table(status_table_name)
        .where(F.col("run_id") == F.lit(run_id))
        .withColumn("status", F.lit(new_status))
    )
    if new_status == 'succeeded':
        updates_df = updates_df.withColumn("_processing_done_ts", F.now())
        upsert_set(spark, status_table_name, updates_df, ['filename', 'run_id'], ['status', '_processing_done_ts'])
    else:
        upsert_set(spark, status_table_name, updates_df, ['filename', 'run_id'], ['status'])


def upsert_set(spark, table_name: str, source_df: DataFrame,
                 merge_cond: List[str], update_cols: List[str]):
    """Perform an upsert (merge) into a Delta table from a source DataFrame.

    Args:
        spark (pyspark.sql.SparkSession): Active Spark session.
        table_name (str): Fully qualified target Delta table name.
        source_df (pyspark.sql.DataFrame): Source rows to merge.
        merge_cond (List[str]): List of equality conditions joining source to target,
            expressed as column names to be matched between source ``s`` and target ``t``.
        update_cols (List[str]): List of column names to update/insert from ``source_df``.

    Returns:
        None: Executes a Delta Lake merge operation.
    """
    target_df = DeltaTable.forName(spark, table_name)
    merge_key_exprs = (map(lambda x: f"s.{x} = t.{x}", merge_cond))
    merge_cond_str = reduce(lambda x,y: f"{x} AND {y}", merge_key_exprs)
    update_set = {c : f"s.{c}" for c in update_cols}
    (target_df.alias("t")
     .merge(source_df.alias("s"), F.expr(merge_cond_str))
     .whenMatchedUpdate(set=update_set)
     .whenNotMatchedInsertAll()
     .execute()
    )


def get_total_executor_cores(spark, sc) -> int:
    """Compute total executor cores (executors * cores) with safe fallbacks.

    Tries to count active executors via the JVM API and multiply by
    spark.executor.cores when configured. Falls back to deriving a per-executor
    core estimate from defaultParallelism or returning defaultParallelism if
    executor details are unavailable.

    Args:
        spark (pyspark.sql.SparkSession): Active Spark session.
        sc (pyspark.SparkContext): Active Spark context.

    Returns:
        int: Estimated total number of executor cores available to the job.
    """
    try:
        jstatus = sc._jsc.sc().getExecutorMemoryStatus()
        keys = list(jstatus.keySet().toArray())
        executor_nodes = [str(k) for k in keys if 'driver' not in str(k).lower()]
        executor_count = len(executor_nodes)
        try:
            exec_cores = int(spark.conf.get("spark.executor.cores"))
        except Exception:
            exec_cores = None
        if executor_count > 0 and exec_cores and exec_cores > 0:
            return executor_count * exec_cores
        if executor_count > 0:
            per_exec = max(1, int(sc.defaultParallelism / executor_count))
            return per_exec * executor_count
        return sc.defaultParallelism
    except Exception:
        return sc.defaultParallelism


def table_exists(spark, catalog: str, schema: str, table_name: str):
    """Check whether a table exists by querying information_schema.

    This version overrides the earlier ``table_exists`` using Spark's catalog API.

    Args:
        spark (pyspark.sql.SparkSession): Active Spark session.
        catalog (str): Catalog name.
        schema (str): Schema name.
        table_name (str): Table name.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    query = spark.sql(f"""
            SELECT 1 
            FROM {catalog}.information_schema.tables 
            WHERE table_name = '{table_name}' 
            AND table_schema='{schema}' LIMIT 1""",
        )
    return query.count() > 0
  

def _unzip_archive(zip_path, extract_to):
    """Extract all contents of a zip archive to a target directory.

    Args:
        zip_path (str): Path to the zip file.
        extract_to (str): Directory where the archive contents will be extracted.
    """
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)


def _get_obd_signals(file_path, date):
    """Read an OBD CSV file and construct signal arrays compatible with ASAM MDF.

    The function expects a CSV file with a ``Time`` column and multiple signal columns.
    It computes a synthetic master timestamp column in microseconds and returns the
    aligned master timestamps and a mapping of signal names to numeric arrays.

    Args:
        file_path (str): Path to the CSV file.
        date (str): Date string (YYYY-MM-DD) used when building the timestamp.

    Returns:
        Tuple[List[int], Dict[str, List[float]]]: Master timestamps and signal values.
    """
    pdf = pd.read_csv(file_path)
    pdf['date'] = date
    pdf['master'] = (pd.to_datetime(pdf['date'].astype(str) + ' ' + pdf['Time'].astype(str)).astype(int) / 10**3).astype(int)
    pdf = pdf.dropna()
    master = list(pdf['master'])
    signals = {col: list(pdf[col].astype(float)) for col in pdf.drop(["Time", "date", "master"], axis=1).columns}
    return master, signals


def convert_obd_data(input_path: str, local_tmp_dir: str, output_dir: str,
                          replication_factor: int, dbutils):
    """Convert and package OBD CSV demo data into MDF (ASAM MDF v4) files.

    Requires asammdf: install via ``%pip install 'numpy<2' asammdf==8.7.2``.

    If ``input_path`` is a zip file, it is extracted into ``local_tmp_dir``. The function
    then iterates over the dataset, converts signals into MDF groups using ``asammdf``,
    optionally replicates signals to extend duration, writes the MDF files to a temp
    directory, and copies to ``output_dir`` using ``dbutils.fs.cp``.

    Args:
        input_path (str): Path to the input OBD dataset or zip archive.
        local_tmp_dir (str): Local directory for temporary extraction and staging.
        output_dir (str): Destination root directory in DBFS/Unity FS.
        replication_factor (int): Number of times to repeat signals to extend duration.
        dbutils: Databricks utilities object for filesystem operations.

    Returns:
        None
    """
    if os.path.isfile(input_path):
        _unzip_archive(input_path, local_tmp_dir)
    else:
        local_tmp_dir = '../data/'
    listing = glob.glob(f"{local_tmp_dir}/obd_dataset/*")
    for sim_data_path in listing:
        experiment_id = sim_data_path.split('/')[-1]
        #check if the data of the current experiment already exists in the output dir
        if os.path.exists(f"{output_dir}/{experiment_id}"):
            continue

        mdf_file_written = False
        unit_pattern = r'\[([^\]]+)\]'
        for csv_file_path in os.listdir(sim_data_path):
            try:
                file_path = f"{sim_data_path}/{csv_file_path}"
                file_name = csv_file_path.replace(".csv", "")
                tmp_mdf_path = f"/tmp/{experiment_id}/{file_name}.mf4"
                (date, brand, model, from_city, to_city, condition) = file_name.split("_")[:6]
                master, signals = _get_obd_signals(file_path, date)
                
                if replication_factor > 0:
                    master, signals = _replicate_signals(master, signals, replication_factor)
                data_groups = _create_data_groups(signals)
                comment=f"{{'brand': '{brand}', 'model': '{model}', 'vehicle_key': '{brand}_{model}', 'from_city': '{from_city}', 'to_city': '{to_city}', 'condition': '{condition}', 'experiment_id': '{experiment_id}'}}"
                from asammdf import MDF, Signal  # lazy import — heavy dep
                mdf = MDF(version='4.10')
                mdf.header.comment = comment
                for data_group in data_groups:
                    current_mdf_signals = []
                    for k,v in data_group.items():
                        name = k[:k.find(' [')]
                        unit = re.findall(unit_pattern, k)[-1]
                        if unit in ['Â°C', '°C']:
                            unit = 'C'
                        sig = Signal(samples=v,
                                        timestamps=master,
                                        name=name,
                                        unit=unit,
                                        comment=comment
                                        )
                        current_mdf_signals.append(sig)
                    mdf.append(current_mdf_signals)
                res = mdf.save(tmp_mdf_path, overwrite=True)
                mdf_file_written = True
            except Exception as e:
                print(e)
                continue
        if mdf_file_written:
            dbutils.fs.cp(f"file:///tmp/{experiment_id}", f"{output_dir}/{experiment_id}", recurse=True)
            break


def _replicate_signals(master: list, signals: dict, replication_factor: int) -> tuple:
    """Replicate a set of signals and timestamps to extend a simulated drive.

    Each replication appends the original signals and shifts the timestamps by the
    last timestamp of the replicated sequence.

    Args:
        master (List[int]): Original master timestamps.
        signals (Dict[str, List[float]]): Mapping from signal name to values.
        replication_factor (int): How many times to repeat the sequence.

    Returns:
        Tuple[List[int], Dict[str, List[float]]]: Replicated timestamps and signals.
    """
    replicated_master = master
    replicated_signals = signals.copy()
    for i in range(replication_factor):
        last_ts = replicated_master[-1]
        new_master = [i + last_ts for i in master]
        replicated_master = replicated_master + new_master
        for signal_name in replicated_signals.keys():
            replicated_signals[signal_name] = replicated_signals[signal_name] + signals[signal_name]
    return (replicated_master, replicated_signals)


def _create_data_groups(signals: list) -> list:
    """Split signals into a random number of data groups for MDF writing.

    Args:
        signals (Dict[str, List[float]]): Mapping from signal name to values.

    Returns:
        List[Dict[str, List[float]]]: A list of smaller dictionaries (data groups).
    """
    group_count = np.random.randint(1, 10)
    data_groups = [{} for i in range(group_count)]
    for i, k in enumerate(signals):
        data_groups[i % group_count][k] = signals[k]
    return data_groups
