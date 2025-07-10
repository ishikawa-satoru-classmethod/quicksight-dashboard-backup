# AWS QuickSight Dashboard Backup Tool

A Python tool for automatically backing up AWS QuickSight dashboards as asset bundles. Supports both local storage and S3 bucket storage with intelligent fallback mechanisms.

## 🚀 Features

- **Automated Backup**: Export all QuickSight dashboards with a single command
- **Dual Storage Options**: Save to S3 bucket or local directory with automatic fallback
- **Smart Organization**: ISO8601 date-based folder structure for easy management
- **Zero Configuration**: Auto-detects AWS account ID from current credentials
- **Comprehensive Error Handling**: Robust retry logic with exponential backoff
- **AWS Lambda Ready**: Deploy as a serverless function for scheduled backups
- **Secure**: No hardcoded credentials, uses AWS IAM roles and profiles

## 📋 Prerequisites

- Python 3.7+
- AWS CLI configured or IAM role with appropriate permissions
- QuickSight access in your AWS account

### Required AWS Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "quicksight:ListDashboards",
        "quicksight:StartAssetBundleExportJob",
        "quicksight:DescribeAssetBundleExportJob",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::your-backup-bucket/*"
    }
  ]
}
```

## 🛠️ Installation

1. Clone the repository:
```bash
git clone https://github.com/ishikawa-satoru-classmethod/quicksight-dashboard-backup.git
cd quicksight-dashboard-backup
```

2. Install dependencies:
```bash
pip install boto3 requests
```

3. Configure AWS credentials (choose one):
```bash
# Option 1: AWS CLI
aws configure

# Option 2: Environment variables
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_DEFAULT_REGION=us-east-1

# Option 3: IAM role (recommended for EC2/Lambda)
# No additional configuration needed
```

## 🎯 Quick Start

### Basic Usage (Local Storage)
```bash
python quicksight_dashboard_backup.py
```

### S3 Storage
```bash
export S3_BUCKET_NAME='my-quicksight-backups'
python quicksight_dashboard_backup.py
```

### With Custom Configuration
```bash
export PROFILE_NAME='production'
export S3_BUCKET_NAME='company-quicksight-backups'
export S3_KEY_PREFIX='dashboards/production'
export LOG_LEVEL='debug'
python quicksight_dashboard_backup.py
```

## ⚙️ Configuration

### Environment Variables

All configuration is optional with sensible defaults:

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `ACCOUNT_ID` | AWS Account ID | Auto-detected | `123456789012` |
| `PROFILE_NAME` | AWS Profile | Default credentials | `production` |
| `REGION_NAME` | AWS Region | `us-east-1` | `ap-northeast-1` |
| `S3_BUCKET_NAME` | S3 Bucket for backups | Local storage | `my-backup-bucket` |
| `S3_KEY_PREFIX` | S3 Key prefix | Empty | `quicksight/backups` |
| `LOG_LEVEL` | Logging level | `info` | `debug` |
| `BACKUP_DIR` | Local backup directory | `backup` | `/opt/backups` |

### Using .env File

Create a `.env` file from the example:
```bash
cp .env.example .env
# Edit .env with your preferred settings
```

Example `.env` configuration:
```bash
# AWS Configuration
PROFILE_NAME=my-profile
REGION_NAME=us-east-1

# S3 Storage (optional)
S3_BUCKET_NAME=my-quicksight-backups
S3_KEY_PREFIX=production/dashboards

# Logging
LOG_LEVEL=info
```

## 📁 Output Structure

### Local Storage
```
backup/
├── Dashboard_Sales_Report.qs
├── Dashboard_Analytics.qs
└── Dashboard_Finance.qs
```

### S3 Storage
```
s3://my-backup-bucket/
└── production/dashboards/     # S3_KEY_PREFIX
    └── 2023-12-25/           # ISO8601 date
        ├── Dashboard_Sales_Report.qs
        ├── Dashboard_Analytics.qs
        └── Dashboard_Finance.qs
```

## 🚀 AWS Lambda Deployment

The script includes a Lambda handler for serverless execution:

### Deployment Package
```bash
# Create deployment package
zip -r quicksight-backup.zip quicksight_dashboard_backup.py

# Add dependencies
pip install boto3 requests -t .
zip -r quicksight-backup.zip boto3/ requests/ urllib3/ certifi/ charset_normalizer/ idna/ botocore/ dateutil/ jmespath/ s3transfer/
```

### Lambda Configuration
- **Runtime**: Python 3.9+
- **Handler**: `quicksight_dashboard_backup.lambda_handler`
- **Timeout**: 15 minutes
- **Memory**: 512 MB
- **Environment Variables**: Set as needed

### CloudWatch Events for Scheduling
```json
{
  "Rules": [
    {
      "Name": "QuickSightBackupSchedule",
      "ScheduleExpression": "cron(0 2 * * ? *)",
      "Targets": [
        {
          "Id": "QuickSightBackupTarget",
          "Arn": "arn:aws:lambda:region:account:function:quicksight-backup"
        }
      ]
    }
  ]
}
```

> **Note**: For environments with large numbers of dashboards or expected execution times exceeding 15 minutes, use AWS Glue Python Shell jobs as an alternative to AWS Lambda timeout limitations.

## 🔍 Monitoring and Logging

### Log Levels
- **INFO**: Standard operational messages
- **DEBUG**: Detailed execution information including AWS API calls

### Sample Output
```
Starting QuickSight dashboard backup for account: 123456789012
Found 5 dashboards to backup
Phase 1: Starting export jobs with limited concurrency (max 3)...
[1/5] Starting export: Sales management table by department
[2/5] Starting export: sale
[3/5] Starting export: Sales Profit and Loss Dashboard
  ✓ sale: Export job started
[4/5] Starting export: dashboard20220902
  ✓ dashboard20220902: Export job started
[5/5] Starting export: Cost-and-usage-QuickSight-dashboard-in-us-east-1
  ✓ Sales Profit and Loss Dashboard: Export job started
  ✓ Sales management table by department: Export job started
  ✓ Cost-and-usage-QuickSight-dashboard-in-us-east-1: Export job started
Phase 1 complete: 7 jobs started, 0 failed to start
Phase 2: Monitoring jobs and downloading results concurrently...
Using 5 concurrent threads for monitoring and downloading
[2/5] Monitoring: sale
[4/5] Monitoring: dashboard20220902
[3/5] Monitoring: Sales Profit and Loss Dashboard
[1/5] Monitoring: Sales management table by department
[5/5] Monitoring: Cost-and-usage-QuickSight-dashboard-in-us-east-1
  ✗ Sales Profit and Loss Dashboard: Export job failed: The data set type is not supported through API yet
  ✓ sale: Backup completed successfully
  ✓ dashboard20220902: Backup completed successfully
  ✗ Sales management table by department: Export job failed: The data set type is not supported through API yet
  ✓ Cost-and-usage-QuickSight-dashboard-in-us-east-1: Backup completed successfully
Phase 2 complete: All jobs monitored and downloads attempted

Backup completed in 77.7 seconds

============================================================
BACKUP REPORT
============================================================
Total dashboards: 5
Successful backups: 3
Failed backups: 2

Successful backups:
  ✓ sale (2025-07-09 10:06:33)
  ✓ dashboard20220902 (2025-07-09 10:06:33)
  ✓ Cost-and-usage-QuickSight-dashboard-in-us-east-1 (2025-07-09 10:07:03)

Failed backups:
  ✗ Sales Profit and Loss Dashboard - FAILED (2025-07-09 10:06:31)
  ✗ Sales management table by department - FAILED (2025-07-09 10:06:35)

Backup files saved to: s3://cm-quicksight-backup-20250708/
============================================================
```

## 🛡️ Security Best Practices

- **No Hardcoded Credentials**: Uses AWS IAM roles and profiles
- **Least Privilege**: Only requires necessary QuickSight and S3 permissions
- **Secure Storage**: Backups are encrypted at rest in S3
- **Audit Trail**: Comprehensive logging for security monitoring

## 🔧 Troubleshooting

### Common Issues

**"Unable to retrieve AWS Account ID"**
- Ensure AWS credentials are properly configured
- Check IAM permissions for `sts:GetCallerIdentity`

**"S3 upload failed, falling back to local storage"**
- Verify S3 bucket exists and is accessible
- Check IAM permissions for `s3:PutObject`

**"No dashboards found to backup"**
- Verify QuickSight access in the target account
- Ensure dashboards exist in the specified region

**"The data set type is not supported through API yet"**
- This error occurs when the dataset uses S3 or uploaded files, which are not supported by the API
- Consider reconfiguring data access through Amazon Athena to avoid this error

### Debug Mode
```bash
export LOG_LEVEL=debug
python quicksight_dashboard_backup.py
```

## 📄 License

This project is released under the Apache License 2.0. See LICENSE file for details.

