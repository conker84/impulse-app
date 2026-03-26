import pyspark.sql.types as T

def get_mdf4_schemas():
  return {
    'tags_schema': T.StructType([
      T.StructField('container_id', T.LongType(), nullable=False),
      T.StructField('key', T.StringType()),
      T.StructField('value', T.StringType())
      ]),
    'metrics_schema': T.StructType([
      T.StructField('container_id', T.LongType(), nullable=False),
      T.StructField('vehicle_key', T.StringType()),
      T.StructField('start_ts', T.LongType()),
      T.StructField('stop_ts', T.LongType()),
      T.StructField('start_dt', T.TimestampType()),
      T.StructField('stop_dt', T.TimestampType()),
      T.StructField('duration_ms', T.IntegerType()),
      T.StructField('num_channels', T.IntegerType())
      ]),
    'bronze_schema': T.StructType([
      T.StructField('filename', T.StringType(), nullable=False),
      T.StructField('channel_id', T.IntegerType(), nullable=False),
      T.StructField('group_idx', T.IntegerType(), nullable=False),
      T.StructField('channel_idx', T.IntegerType(), nullable=False),
      T.StructField('channel_name', T.StringType(), nullable=False),
      T.StructField('unit', T.StringType(), nullable=False),
      T.StructField('time', T.LongType(), nullable=False),
      T.StructField('value', T.DoubleType(), nullable=False),
      T.StructField('brand', T.StringType(), nullable=False),
      T.StructField('model', T.StringType(), nullable=False),
      T.StructField('vehicle_key', T.StringType(), nullable=False),
      T.StructField('from_city', T.StringType(), nullable=False),
      T.StructField('to_city', T.StringType(), nullable=False),
      T.StructField('condition', T.StringType(), nullable=False),
      T.StructField('experiment_id', T.StringType(), nullable=False)
      ]),
    'silver_schema': T.StructType([
      T.StructField('filename', T.StringType(), nullable=False),
      T.StructField('group_idx', T.IntegerType(), nullable=False),
      T.StructField('channel_idx', T.IntegerType(), nullable=False),
      T.StructField('tstart', T.LongType(), nullable=False),
      T.StructField('tend', T.LongType(), nullable=False),
      T.StructField('value', T.DoubleType(), nullable=False),    
      ])
  }
