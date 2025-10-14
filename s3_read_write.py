# `aws configure` to set up the credentials (see them in Discord private channel)
# choose `uw-west-2` and `json` output format

#%%
import boto3

s3 = boto3.client("s3")

#%%
# Write a file to S3
bucket_name = "arxiv-full-dataset"
file_path = "example_file.txt"
with open(file_path, "w", encoding="utf-8") as f:
    f.write("This is a file created for upload.\n")
print(f"Created local file: {file_path}")
object_name = "example_file.txt"  # name inside S3

s3.upload_file(file_path, bucket_name, object_name)
print("✅ Upload complete.")

#%%
# Read the file back from S3
s3.download_file(bucket_name, object_name, "new_example_file.txt")
print("✅ Download complete.")
