# AWS QuickSight ダッシュボード バックアップ ツール

AWS QuickSight ダッシュボードをアセットバンドルとして自動バックアップするPythonツールです。ローカルストレージとS3バケットストレージの両方をサポートし、インテリジェントなフォールバック機能を提供します。

## 🚀 機能

- **自動バックアップ**: 単一のコマンドですべてのQuickSightダッシュボードをエクスポート
- **デュアルストレージオプション**: S3バケットまたはローカルディレクトリに保存、自動フォールバック機能付き
- **スマートな整理**: 簡単な管理のためのISO8601日付ベースのフォルダ構造
- **ゼロコンフィグレーション**: 現在の認証情報からAWSアカウントIDを自動検出
- **包括的なエラーハンドリング**: 指数バックオフによる堅牢な再試行ロジック
- **AWS Lambda対応**: スケジュールされたバックアップ用のサーバーレス関数としてデプロイ可能
- **セキュア**: ハードコードされた認証情報なし、AWS IAMロールとプロファイルを使用

## 📋 前提条件

- Python 3.7+
- AWS CLI設定またはIAMロールと適切な権限
- AWSアカウントでのQuickSightアクセス

### 必要なAWS権限

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

## 🛠️ インストール

1. リポジトリをクローン:
```bash
git clone <repository-url>
cd quicksight-dashboard-backup
```

2. 依存関係をインストール:
```bash
pip install boto3 requests
```

3. AWS認証情報を設定（以下のいずれかを選択）:
```bash
# オプション1: AWS CLI
aws configure

# オプション2: 環境変数
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_DEFAULT_REGION=us-east-1

# オプション3: IAMロール（EC2/Lambda推奨）
# 追加の設定は不要
```

## 🎯 クイックスタート

### 基本的な使用方法（ローカルストレージ）
```bash
python quicksight_dashboard_backup.py
```

### S3ストレージ
```bash
export S3_BUCKET_NAME='my-quicksight-backups'
python quicksight_dashboard_backup.py
```

### カスタム設定
```bash
export PROFILE_NAME='production'
export S3_BUCKET_NAME='company-quicksight-backups'
export S3_KEY_PREFIX='dashboards/production'
export LOG_LEVEL='debug'
python quicksight_dashboard_backup.py
```

## ⚙️ 設定

### 環境変数

すべての設定は適切なデフォルト値を持つオプションです：

| 変数 | 説明 | デフォルト | 例 |
|----------|-------------|---------|---------|
| `ACCOUNT_ID` | AWS アカウント ID | 自動検出 | `123456789012` |
| `PROFILE_NAME` | AWS プロファイル | デフォルト認証情報 | `production` |
| `REGION_NAME` | AWS リージョン | `us-east-1` | `ap-northeast-1` |
| `S3_BUCKET_NAME` | バックアップ用S3バケット | ローカルストレージ | `my-backup-bucket` |
| `S3_KEY_PREFIX` | S3キープレフィックス | 空 | `quicksight/backups` |
| `LOG_LEVEL` | ログレベル | `info` | `debug` |
| `BACKUP_DIR` | ローカルバックアップディレクトリ | `backup` | `/opt/backups` |

### .envファイルの使用

サンプルから.envファイルを作成:
```bash
cp .env.example .env
# .envファイルを希望の設定で編集
```

.envファイルの例:
```bash
# AWS設定
PROFILE_NAME=my-profile
REGION_NAME=us-east-1

# S3ストレージ（オプション）
S3_BUCKET_NAME=my-quicksight-backups
S3_KEY_PREFIX=production/dashboards

# ログ
LOG_LEVEL=info
```

## 📁 出力構造

### ローカルストレージ
```
backup/
├── Dashboard_Sales_Report.qs
├── Dashboard_Analytics.qs
└── Dashboard_Finance.qs
```

### S3ストレージ
```
s3://my-backup-bucket/
└── production/dashboards/     # S3_KEY_PREFIX
    └── 2023-12-25/           # ISO8601 日付
        ├── Dashboard_Sales_Report.qs
        ├── Dashboard_Analytics.qs
        └── Dashboard_Finance.qs
```

## 🚀 AWS Lambda デプロイ

スクリプトはサーバーレス実行のためのLambdaハンドラーを含んでいます：

### デプロイメントパッケージ
```bash
# デプロイメントパッケージを作成
zip -r quicksight-backup.zip quicksight_dashboard_backup.py

# 依存関係を追加
pip install boto3 requests -t .
zip -r quicksight-backup.zip boto3/ requests/ urllib3/ certifi/ charset_normalizer/ idna/ botocore/ dateutil/ jmespath/ s3transfer/
```

### Lambda設定
- **ランタイム**: Python 3.9+
- **ハンドラー**: `quicksight_dashboard_backup.lambda_handler`
- **タイムアウト**: 15分
- **メモリ**: 512 MB
- **環境変数**: 必要に応じて設定

### スケジュール用CloudWatch Events
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

> **注**: 大量のダッシュボードを持つ環境や15分を超える実行時間が予想される場合、AWS Lambdaのタイムアウト制限の代替手段としてAWS Glue Python Shellジョブを使用してください。

## 🔍 監視とログ

### ログレベル
- **INFO**: 標準的な運用メッセージ
- **DEBUG**: AWS API呼び出しを含む詳細な実行情報

### サンプル出力
```
Starting QuickSight dashboard backup for account: 517444948157
Found 5 dashboards to backup
Phase 1: Starting export jobs with limited concurrency (max 3)...
[1/5] Starting export: 部門別販売管理表
[2/5] Starting export: sale
[3/5] Starting export: 販売損益ダッシュボード
  ✓ sale: Export job started
[4/5] Starting export: dashboard20220902
  ✓ dashboard20220902: Export job started
[5/5] Starting export: Cost-and-usage-QuickSight-dashboard-in-us-east-1
  ✓ 販売損益ダッシュボード: Export job started
  ✓ 部門別販売管理表: Export job started
  ✓ Cost-and-usage-QuickSight-dashboard-in-us-east-1: Export job started
Phase 1 complete: 7 jobs started, 0 failed to start
Phase 2: Monitoring jobs and downloading results concurrently...
Using 5 concurrent threads for monitoring and downloading
[2/5] Monitoring: sale
[4/5] Monitoring: dashboard20220902
[3/5] Monitoring: 販売損益ダッシュボード
[1/5] Monitoring: 部門別販売管理表
[5/5] Monitoring: Cost-and-usage-QuickSight-dashboard-in-us-east-1
  ✗ 販売損益ダッシュボード: Export job failed: The data set type is not supported through API yet
  ✓ sale: Backup completed successfully
  ✓ dashboard20220902: Backup completed successfully
  ✗ 部門別販売管理表: Export job failed: The data set type is not supported through API yet
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
  ✗ 販売損益ダッシュボード - FAILED (2025-07-09 10:06:31)
  ✗ 部門別販売管理表 - FAILED (2025-07-09 10:06:35)

Backup files saved to: s3://cm-quicksight-backup-20250708/
============================================================
```

## 🛡️ セキュリティベストプラクティス

- **ハードコードされた認証情報なし**: AWS IAMロールとプロファイルを使用
- **最小権限**: 必要なQuickSightとS3権限のみ
- **セキュアなストレージ**: S3でのバックアップは保存時暗号化
- **監査証跡**: セキュリティ監視のための包括的ログ

## 🔧 トラブルシューティング

### よくある問題

**"AWS Account IDを取得できません"**
- AWS認証情報が適切に設定されていることを確認
- `sts:GetCallerIdentity`のIAM権限を確認

**"S3アップロードに失敗、ローカルストレージにフォールバック"**
- S3バケットが存在しアクセス可能であることを確認
- `s3:PutObject`のIAM権限を確認

**"バックアップするダッシュボードが見つかりません"**
- 対象アカウントでのQuickSightアクセスを確認
- 指定されたリージョンにダッシュボードが存在することを確認

**"The data set type is not supported through API yet"**
- S3やアップロードファイルのデータセットの場合、APIがサポートしていないためエラーになります
- データファイルをAmazon Athena経由でアクセスするように見直すことでエラーを回避できます

### デバッグモード
```bash
export LOG_LEVEL=debug
python quicksight_dashboard_backup.py
```

## 📄 ライセンス

このプロジェクトはApache License 2.0の下でリリースされています。詳細はLICENSEファイルを参照してください。

