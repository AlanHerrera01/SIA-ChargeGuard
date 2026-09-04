# Infrastructure as Code

Terraform configuration for the AWS account.

## Owner
Ismael

## What's here
- DynamoDB tables
- S3 buckets
- IAM roles (including OIDC role for GitHub Actions)
- EventBridge rules
- Lambda functions
- API Gateway
- Amplify Hosting

## Deploy
```bash
cd infrastructure
terraform init
terraform plan
terraform apply
```
