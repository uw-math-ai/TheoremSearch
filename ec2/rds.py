import os
import psycopg2
import boto3
import json
from psycopg2.extensions import connection
import dotenv

dotenv.load_dotenv()

def get_rds_connection() -> connection:
    """
    Provides a connection to the AWS RDS database.

    Returns
    -------
    conn: connection
        Connection to the RDS database
    """

    region = os.getenv("AWS_REGION", "us-west-2")
    secret_arn = os.getenv("RDS_SECRET_ARN")
    host = os.getenv("RDS_HOST", "")
    dbname = "postgres"

    sm = boto3.client("secretsmanager", region_name=region)
    secret_value = sm.get_secret_value(SecretId=secret_arn)
    secret_dict = json.loads(secret_value["SecretString"])

    conn = psycopg2.connect(
        host=host or secret_dict.get("host"),
        port=int(secret_dict.get("port", 5432)),
        dbname=dbname or secret_dict.get("dbname", "postgres"),
        user=secret_dict["username"],
        password=secret_dict["password"],
        sslmode="require",
    )
    return conn