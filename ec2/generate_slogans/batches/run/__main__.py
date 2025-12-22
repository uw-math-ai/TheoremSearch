import boto3
import os
from ...models import MODELS
from ..config import S3_BUCKET, S3_DIR

bedrock = boto3.client("bedrock", region_name=os.getenv("AWS_REGION"))

def run_batch_job(
    model_name: str,
    job_id: str
):
    model_id = MODELS[model_name]["model_id"]

    res = bedrock.create_model_invocation_job(
        jobName=job_id,
        modelId=model_id,
        roleArn=os.getenv("RDS_SECRET_ARN"),
        inputDataConfig={
            "s3InputDataConfig": {"s3Uri": f"s3://{S3_BUCKET}/{S3_DIR}/{job_id}/in"}
        },
        outputDataConfig={
            "s3OutputDataConfig": {"s3Uri": f"s3://{S3_BUCKET}/{S3_DIR}/{job_id}/out"}
        }
    )

    return res["jobArn"]

if __name__ == "__main__":
    run_batch_job("DeepSeek-V3.1", job_id="0f41b4b8-ddf4-11f0-aac8-00163e5a2b6a")