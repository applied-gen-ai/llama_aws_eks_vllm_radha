terraform {
  backend "s3" {
    bucket = "kubernetes-terraform-api"
    key    = "eks-cluster/terraform.tfstate"
    region = "us-east-1"        # <-- Use the actual S3 bucket region
    # use_lockfile replaces deprecated dynamodb_table
    use_lockfile = true
  }
}