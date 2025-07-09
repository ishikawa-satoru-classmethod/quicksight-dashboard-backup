#!/usr/bin/env python3
"""
AWS QuickSight Dashboard Backup Script
AWS QuickSight Dashboard Backup Script

This script exports AWS QuickSight dashboards as asset bundles and saves them
locally or to S3. It can be executed as a standalone script or deployed as
an AWS Lambda function.

Key features:
- Export all dashboards from QuickSight account
- Save to local directory or S3 bucket
- Detailed logging at debug/info levels
- Configuration support via environment variables and .env file
- Retry logic with exponential backoff
- Comprehensive backup report generation
"""

import boto3
import json
import time
import requests
import os
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# ========================================
# Configuration Constants
# ========================================

# Default configuration values
DEFAULT_REGION = 'us-east-1'
DEFAULT_LOG_LEVEL = 'info'
DEFAULT_BACKUP_DIR = 'backup'

# Job status polling configuration
MAX_RETRIES = 7                    # Maximum retry attempts
BASE_DELAY_SECONDS = 4             # Base delay time (seconds)
EXPORT_FORMAT = 'QUICKSIGHT_JSON'  # Export format

# Export job start retry configuration (for LimitExceededException)
EXPORT_START_MAX_RETRIES = 10          # Maximum retry attempts
EXPORT_START_BASE_DELAY_SECONDS = 5    # Base delay time (seconds)

# File download configuration
DOWNLOAD_TIMEOUT_SECONDS = 300     # Download timeout (5 minutes)
FILENAME_MAX_LENGTH = 200          # Maximum filename length

# Concurrent processing configuration
MAX_EXPORT_START_WORKERS = 3       # Maximum concurrent export starts
MAX_MONITOR_WORKERS = 32           # Maximum concurrent monitoring

# ========================================
# Environment Configuration
# ========================================

def load_env_file() -> None:
    """
    Load environment variables from .env file.
    
    If .env file exists, its contents are set as environment variables.
    Existing environment variables are not overwritten.
    """
    env_file = Path('.env')
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comment lines
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Remove surrounding quotes
                    value = value.strip('"\'')
                    # Set only if not already set in environment variables
                    if key not in os.environ:
                        os.environ[key] = value

# Load .env file before configuration
load_env_file()

# ========================================
# Global Configuration
# ========================================

# AWS configuration (from environment variables or .env file)
ACCOUNT_ID = os.environ.get('ACCOUNT_ID')           # Optional - auto-detected if not provided
PROFILE_NAME = os.environ.get('PROFILE_NAME')       # Optional - AWS profile name
REGION_NAME = os.environ.get('REGION_NAME', DEFAULT_REGION)

# S3 configuration
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')   # Required for S3 storage
S3_KEY_PREFIX = os.environ.get('S3_KEY_PREFIX', '') # Optional - S3 key prefix

# Script configuration
LOG_LEVEL = os.environ.get('LOG_LEVEL', DEFAULT_LOG_LEVEL)
BACKUP_DIR = os.environ.get('BACKUP_DIR', DEFAULT_BACKUP_DIR)  # Fallback when S3 not configured

# ========================================
# Logging Configuration
# ========================================

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def log_info(message: str) -> None:
    """Output information message to log."""
    logger.info(message)

def log_debug(message: str) -> None:
    """Output debug message to log if debug mode is enabled."""
    if LOG_LEVEL.lower() == 'debug':
        logger.info(f'[DEBUG] {message}')

def sanitize_filename(filename: str) -> str:
    """
    Remove invalid characters from filename to generate a safe filename.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename
    """
    # Remove invalid filename characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove control characters
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '_', sanitized)
    # Remove leading/trailing whitespace and periods
    sanitized = sanitized.strip(' .')
    # Prevent empty filenames
    if not sanitized:
        sanitized = 'unnamed_dashboard'
    # Limit length to accommodate filesystem constraints
    if len(sanitized) > FILENAME_MAX_LENGTH:
        sanitized = sanitized[:FILENAME_MAX_LENGTH]
    return sanitized

# ========================================
# AWS Client Configuration
# ========================================

def create_aws_session() -> boto3.Session:
    """
    Create AWS session and configure with optional profile.
    
    Returns:
        Configured AWS session
    """
    session = boto3.Session()
    
    # Use specified profile if available
    if PROFILE_NAME:
        try:
            available_profiles = boto3.Session().available_profiles
            if PROFILE_NAME in available_profiles:
                session = boto3.Session(profile_name=PROFILE_NAME)
                log_debug(f"Using AWS profile: {PROFILE_NAME}")
            else:
                log_debug(f"Profile '{PROFILE_NAME}' not found in available profiles: {available_profiles}")
                log_debug("Using default AWS credentials")
        except Exception as e:
            log_debug(f"AWS profile check error: {e}")
            log_debug("Using default AWS credentials")
    else:
        log_debug("No profile specified, using default AWS credentials")
    
    return session

def get_account_id_from_credentials(session: boto3.Session) -> str:
    """
    Retrieve AWS Account ID from current credentials.
    
    Args:
        session: AWS session
        
    Returns:
        AWS Account ID
        
    Raises:
        Exception: If failed to retrieve account ID
    """
    try:
        sts_client = session.client('sts', region_name=REGION_NAME)
        response = sts_client.get_caller_identity()
        account_id = response['Account']
        log_debug(f"Auto-detected AWS Account ID: {account_id}")
        return account_id
    except Exception as e:
        raise Exception(f"Unable to retrieve AWS Account ID from current credentials: {e}")

def create_quicksight_client(session: boto3.Session) -> boto3.client:
    """
    Create and configure AWS QuickSight client.
    
    Args:
        session: AWS session
        
    Returns:
        Configured QuickSight client
    """
    return session.client('quicksight', region_name=REGION_NAME)

def create_s3_client(session: boto3.Session) -> boto3.client:
    """
    Create and configure AWS S3 client.
    
    Args:
        session: AWS session
        
    Returns:
        Configured S3 client
    """
    return session.client('s3', region_name=REGION_NAME)

# Function aliases for backward compatibility
def create_aws_client(session: boto3.Session) -> boto3.client:
    """Function alias for backward compatibility"""
    return create_quicksight_client(session)

def get_account_id(session: boto3.Session) -> str:
    """Function alias for backward compatibility"""
    return get_account_id_from_credentials(session)

# AWS resource initialization (deferred for testing)
session = None
quicksight_client = None
s3_client = None

def initialize_aws_resources():
    """Initialize AWS resources (session, clients, account ID)."""
    global session, quicksight_client, s3_client, ACCOUNT_ID
    
    if session is None:
        session = create_aws_session()
        quicksight_client = create_quicksight_client(session)
        s3_client = create_s3_client(session)
        
        # Get or validate account ID
        if ACCOUNT_ID:
            log_debug(f"Using provided account ID: {ACCOUNT_ID}")
        else:
            try:
                ACCOUNT_ID = get_account_id_from_credentials(session)
                log_debug(f"Auto-detected account ID: {ACCOUNT_ID}")
            except Exception as e:
                raise ValueError(f"Failed to auto-detect Account ID and none provided in environment: {e}")
    
    return session, quicksight_client, s3_client, ACCOUNT_ID

# ========================================
# Backup Directory Setup
# ========================================

def setup_backup_directory() -> None:
    """Create local backup directory (fallback when S3 not configured)."""
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        log_debug(f'Created backup directory: {BACKUP_DIR}')

setup_backup_directory()

# ========================================
# Global State
# ========================================

# Store backup results for reporting
backup_results: List[Dict[str, Any]] = []

# ========================================
# Utility Functions
# ========================================

def create_export_job_params(account_id: str, resource_arn: str, job_id: str) -> Dict[str, Any]:
    """
    Create parameters for asset bundle export job.
    
    Args:
        account_id: AWS Account ID
        resource_arn: Dashboard ARN
        job_id: Unique job identifier
        
    Returns:
        Dictionary containing export job parameters
    """
    return {
        "AwsAccountId": account_id,
        "AssetBundleExportJobId": job_id,
        "ResourceArns": [resource_arn],
        "IncludeAllDependencies": True,
        "IncludePermissions": True,
        "ExportFormat": EXPORT_FORMAT
    }

def generate_s3_key(filename: str) -> str:
    """
    Generate S3 key with ISO8601 date folder structure.
    
    Args:
        filename: Target filename
        
    Returns:
        Complete S3 key path
    """
    # Get current date in ISO8601 format (YYYY-MM-DD)
    date_folder = datetime.now().strftime('%Y-%m-%d')
    
    # Combine prefix, date folder, and filename
    if S3_KEY_PREFIX:
        # Remove trailing slash from prefix
        prefix = S3_KEY_PREFIX.rstrip('/')
        s3_key = f"{prefix}/{date_folder}/{filename}"
    else:
        s3_key = f"{date_folder}/{filename}"
    
    return s3_key

def validate_download_url(url: str) -> bool:
    """
    Validate download URL.
    
    Args:
        url: URL to validate
        
    Returns:
        True if URL is valid, False if invalid
    """
    return bool(url and url.startswith(('http://', 'https://')))

# ========================================
# Dashboard Management Functions
# ========================================

def get_dashboard_list(account_id: str) -> List[Dict[str, Any]]:
    """
    Get list of all dashboards from QuickSight account.
    
    Args:
        account_id: AWS Account ID
        
    Returns:
        List of dashboard summary objects
    """
    # Ensure AWS resources are initialized
    _, client_instance, _, _ = initialize_aws_resources()
    
    try:
        response = client_instance.list_dashboards(AwsAccountId=account_id)
        dashboards = response.get('DashboardSummaryList', [])
        log_debug(f"Retrieved {len(dashboards)} dashboards from QuickSight")
        return dashboards
    except Exception as e:
        log_info(f"Dashboard retrieval error: {e}")
        return []

def describe_asset_bundle_export_job(account_id: str, job_id: str) -> Dict[str, Any]:
    """
    Get status of asset bundle export job.
    
    Args:
        account_id: AWS Account ID
        job_id: Export job identifier
        
    Returns:
        Job status response
    """
    # Ensure AWS resources are initialized
    _, client_instance, _, _ = initialize_aws_resources()
    
    try:
        response = client_instance.describe_asset_bundle_export_job(
            AwsAccountId=account_id,
            AssetBundleExportJobId=job_id
        )
        return response
    except Exception as e:
        log_debug(f"Export job information retrieval error: {e}")
        return {"JobStatus": "ERROR", "Status": 500}

# ========================================
# Export Job Management
# ========================================

def start_asset_bundle_export_job(account_id: str, dashboard_name: str, resource_arn: str, job_id: str) -> Optional[Dict[str, Any]]:
    """
    Start asset bundle export job for dashboard with retry logic for AWS limits.
    
    AWS QuickSight has a limit of up to 5 concurrent export jobs.
    This function retries with exponential backoff for LimitException.
    
    Args:
        account_id: AWS Account ID
        dashboard_name: Dashboard name
        resource_arn: Dashboard ARN
        job_id: Unique job identifier
        
    Returns:
        Export job response, or None if failed
    """
    log_debug(f"Starting export job - Name: {dashboard_name}, ARN: {resource_arn}, Job ID: {job_id}")
    
    # Ensure AWS resources are initialized
    _, client_instance, _, _ = initialize_aws_resources()
    
    params = create_export_job_params(account_id, resource_arn, job_id)
    
    # Retry logic for LimitException
    for attempt in range(EXPORT_START_MAX_RETRIES):
        try:
            response = client_instance.start_asset_bundle_export_job(**params)
            log_debug(f"Export job successfully started on attempt {attempt + 1}: {json.dumps(response, indent=2, default=str)}")
            return response
            
        except Exception as e:
            # Check if it's a LimitException
            if "LimitExceededException" in str(type(e)) or "export jobs already in progress" in str(e):
                # Handle AWS QuickSight export job limit (5 concurrent jobs)
                if attempt < EXPORT_START_MAX_RETRIES - 1:
                    delay = EXPORT_START_BASE_DELAY_SECONDS * (2 ** attempt)
                    log_debug(f"Export job limit reached for {dashboard_name}, retrying in {delay} seconds (attempt {attempt + 1}/{EXPORT_START_MAX_RETRIES})")
                    time.sleep(delay)
                    continue
                else:
                    log_info(f"  ✗ {dashboard_name}: Failed to start export job after {EXPORT_START_MAX_RETRIES} attempts: {e}")
                    return None
            else:
                # Other exceptions (don't retry)
                log_info(f"  ✗ {dashboard_name}: Failed to start export job: {e}")
                return None
    
    # Should never reach here due to loop structure, but just in case
    log_info(f"  ✗ {dashboard_name}: Failed to start export job: Maximum retry attempts exceeded")
    return None

def extract_error_message(response: Dict[str, Any]) -> str:
    """
    Extract error message from export job response.
    
    Args:
        response: Job status response
        
    Returns:
        Error message string
    """
    errors = response.get('Errors', [])
    if errors:
        return errors[0].get('Message', 'Unknown error')
    return 'Unknown error'

def check_job_status_and_retry(job_id: str, dashboard_name: str, account_id: str) -> str:
    """
    Monitor export job status with exponential backoff retry.
    
    Args:
        job_id: Export job identifier
        dashboard_name: Dashboard name
        account_id: AWS Account ID
        
    Returns:
        Final job status ('SUCCESS', 'FAILED', 'TIMEOUT', etc.)
    """
    for attempt in range(MAX_RETRIES):
        # Get current job status
        response = describe_asset_bundle_export_job(account_id, job_id)
        log_debug(f"Job status response (attempt {attempt + 1}): {response}")
        
        job_status = response.get('JobStatus', '')
        http_status = response.get('Status', '')
        
        # Handle HTTP errors
        if http_status != 200:
            log_debug(f'HTTP error {http_status} during job status check')
            return 'ERROR'
        
        # Handle different job statuses
        if job_status in ['QUEUED_FOR_IMMEDIATE_EXECUTION', 'IN_PROGRESS']:
            # Job is still running, wait with exponential backoff
            delay = BASE_DELAY_SECONDS * (2 ** attempt)
            log_debug(f'Job in progress, retrying in {delay} seconds...')
            time.sleep(delay)
            
        elif job_status == 'SUCCESSFUL':
            # Job completed successfully, download file
            log_debug('Job completed successfully')
            safe_filename = sanitize_filename(dashboard_name)
            filename = f"{safe_filename}.qs"
            download_url = response.get('DownloadUrl', '')
            
            if download_file(download_url, filename):
                log_info(f'  ✓ {dashboard_name}: Backup completed successfully')
                return 'SUCCESS'
            else:
                log_info(f'  ✗ {dashboard_name}: Download failed')
                return 'DOWNLOAD_FAILED'
                
        elif job_status == 'FAILED':
            # Job failed, extract error message
            error_message = extract_error_message(response)
            log_info(f'  ✗ {dashboard_name}: Export job failed: {error_message}')
            return 'FAILED'
            
        else:
            # Unexpected status
            log_debug(f'Unexpected job_status: {job_status}')
            return 'UNEXPECTED_STATUS'
    
    # Maximum retry attempts exceeded
    log_info(f'  ✗ {dashboard_name}: Timeout after {MAX_RETRIES} retry attempts')
    return 'TIMEOUT'

# ========================================
# File Management
# ========================================

def upload_to_s3(content: bytes, filename: str) -> bool:
    """
    Upload file content to S3 bucket.
    
    Args:
        content: File content as bytes
        filename: Target filename
        
    Returns:
        True if upload successful, False if failed
    """
    if not S3_BUCKET_NAME:
        log_debug("S3_BUCKET_NAME not configured, cannot upload to S3")
        return False
    
    # Sanitize filename
    safe_filename = sanitize_filename(filename) if not filename.endswith('.qs') else sanitize_filename(filename[:-3]) + '.qs'
    s3_key = generate_s3_key(safe_filename)
    
    try:
        # Ensure S3 client is initialized
        _, _, s3_client_instance, _ = initialize_aws_resources()
        
        # Upload to S3
        s3_client_instance.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=content,
            ContentType='application/octet-stream'
        )
        
        log_debug(f"File successfully uploaded to S3: s3://{S3_BUCKET_NAME}/{s3_key}")
        return True
        
    except Exception as e:
        log_debug(f"S3 file upload error: {e}")
        return False

def save_file_locally(content: bytes, filename: str) -> bool:
    """
    Save file content to local directory.
    
    Args:
        content: File content as bytes
        filename: Target filename
        
    Returns:
        True if save successful, False if failed
    """
    try:
        safe_filename = sanitize_filename(filename) if not filename.endswith('.qs') else sanitize_filename(filename[:-3]) + '.qs'
        filepath = os.path.join(BACKUP_DIR, safe_filename)
        
        with open(filepath, 'wb') as f:
            f.write(content)
        
        log_debug(f"File successfully saved locally: {filepath}")
        return True
        
    except Exception as e:
        log_debug(f"Local file save error: {e}")
        return False

def download_file(url: str, filename: str) -> bool:
    """
    Download file from URL and save to S3 or local backup directory.
    
    Args:
        url: Download URL
        filename: Target filename
        
    Returns:
        True if download and save successful, False if failed
    """
    # Validate URL
    if not validate_download_url(url):
        log_debug(f"Invalid download URL: {url}")
        return False
    
    try:
        response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        if response.status_code == 200:
            # Check if S3 is configured
            if S3_BUCKET_NAME:
                # Upload to S3
                if upload_to_s3(response.content, filename):
                    log_debug(f"File successfully uploaded to S3: {filename}")
                    return True
                else:
                    log_debug(f"S3 upload failed, falling back to local storage")
                    # Fall back to local storage
            
            # Local storage (fallback or when S3 not configured)
            return save_file_locally(response.content, filename)
        else:
            log_debug(f"File download failed, status code: {response.status_code}")
            return False
            
    except Exception as e:
        log_debug(f"File download error: {e}")
        return False

# ========================================
# Concurrent Processing Functions
# ========================================

def start_single_export_job(dashboard_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Start export job for a single dashboard.
    
    Designed to be used with ThreadPoolExecutor with limited concurrency
    to avoid overloading the AWS API.
    
    Args:
        dashboard_info: Dictionary containing dashboard information
                       - 'dashboard': Dashboard summary object
                       - 'index': Dashboard index for logging
                       - 'total': Total number of dashboards for logging
                       - 'account_id': AWS Account ID
                       
    Returns:
        Dictionary containing start result:
        - 'success': True if job started successfully, False if failed
        - 'job_info': Job information dictionary (on success) or None
        - 'failed_result': Failure result dictionary (on failure) or None
    """
    dashboard = dashboard_info['dashboard']
    index = dashboard_info['index']
    total = dashboard_info['total']
    account_id = dashboard_info['account_id']
    
    # Extract dashboard information with safe defaults
    arn = dashboard.get('Arn', '')
    name = dashboard.get('Name', 'Unknown')
    
    # Validate required fields
    if not arn:
        log_info(f'[{index}/{total}] Skipping {name} - Missing ARN')
        return {
            'success': False,
            'job_info': None,
            'failed_result': {
                'name': name,
                'status': 'MISSING_ARN',
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        }
    
    job_id = arn.split('/')[-1] if arn else f'job_{index}'
    
    log_info(f'[{index}/{total}] Starting export: {name}')
    
    # Start export job
    export_response = start_asset_bundle_export_job(account_id, name, arn, job_id)
    
    if export_response is None:
        # Failed to start export job
        log_info(f'  ✗ {name}: Failed to start export job')
        return {
            'success': False,
            'job_info': None,
            'failed_result': {
                'name': name,
                'status': 'EXPORT_START_FAILED',
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        }
    else:
        # Job started successfully
        log_info(f'  ✓ {name}: Export job started')
        return {
            'success': True,
            'job_info': {
                'job_id': job_id,
                'name': name,
                'account_id': account_id,
                'index': index,
                'total': total
            },
            'failed_result': None
        }

def monitor_and_download_job(job_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Monitor a single export job and download when complete.
    
    This function is designed to be used with ThreadPoolExecutor for
    concurrent processing.
    
    Args:
        job_info: Dictionary containing job information
                 - 'job_id': Export job identifier
                 - 'name': Dashboard name
                 - 'account_id': AWS Account ID
                 - 'index': Dashboard index for logging
                 - 'total': Total number of dashboards for logging
                 
    Returns:
        Backup result dictionary containing status and metadata
    """
    job_id = job_info['job_id']
    name = job_info['name']
    account_id = job_info['account_id']
    index = job_info.get('index', 0)
    total = job_info.get('total', 0)
    
    log_info(f'[{index}/{total}] Monitoring: {name}')
    
    # Monitor job status and download file if successful
    result = check_job_status_and_retry(job_id, name, account_id)
    
    return {
        'name': name,
        'status': result,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

# ========================================
# Phase Management Functions
# ========================================

def execute_phase_1_start_jobs(dashboards: List[Dict[str, Any]], account_id: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Phase 1: Start export jobs with limited concurrency.
    
    Args:
        dashboards: List of dashboards
        account_id: AWS Account ID
        
    Returns:
        Tuple of jobs to monitor list and failed starts
    """
    log_info(f'Phase 1: Starting export jobs with limited concurrency (max {MAX_EXPORT_START_WORKERS})...')
    
    jobs_to_monitor = []
    failed_starts = []
    
    # Prepare dashboard information for concurrent processing
    dashboard_infos = []
    for i, dashboard in enumerate(dashboards, 1):
        dashboard_infos.append({
            'dashboard': dashboard,
            'index': i,
            'total': len(dashboards),
            'account_id': account_id
        })
    
    # Use ThreadPoolExecutor to start export jobs with limited concurrency
    # Use 3 workers to reduce conflicts with AWS's 5 concurrent job limit
    with ThreadPoolExecutor(max_workers=MAX_EXPORT_START_WORKERS) as executor:
        # Submit all start job tasks
        future_to_dashboard_info = {
            executor.submit(start_single_export_job, dashboard_info): dashboard_info 
            for dashboard_info in dashboard_infos
        }
        
        # Collect results as they complete
        completed_starts = 0
        for future in as_completed(future_to_dashboard_info):
            completed_starts += 1
            dashboard_info = future_to_dashboard_info[future]
            
            try:
                result = future.result()
                
                if result['success']:
                    # Job started successfully
                    jobs_to_monitor.append(result['job_info'])
                else:
                    # Job failed to start
                    failed_starts.append(result['failed_result'])
                    
                log_debug(f'Start job completed {completed_starts}/{len(dashboards)}: {dashboard_info["dashboard"].get("Name", "Unknown")} -> {"SUCCESS" if result["success"] else "FAILED"}')
                
            except Exception as e:
                # Handle executor exceptions
                name = dashboard_info['dashboard'].get('Name', 'Unknown')
                log_info(f'  ✗ Exception during export start for {name}: {e}')
                failed_starts.append({
                    'name': name,
                    'status': 'START_EXCEPTION',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
    
    return jobs_to_monitor, failed_starts

def execute_phase_2_monitor_jobs(jobs_to_monitor: List[Dict[str, Any]], max_workers: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Phase 2: Monitor jobs and download results concurrently.
    
    Args:
        jobs_to_monitor: List of jobs to monitor
        max_workers: Maximum concurrent threads for monitoring/downloading
        
    Returns:
        List of backup results
    """
    log_info('Phase 2: Monitoring jobs and downloading results concurrently...')
    
    # Determine optimal worker thread count
    if max_workers is None:
        max_workers = min(MAX_MONITOR_WORKERS, len(jobs_to_monitor))
    
    log_info(f'Using {max_workers} concurrent threads for monitoring and downloading')
    
    results = []
    
    # Use ThreadPoolExecutor to monitor jobs concurrently
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all monitoring tasks
        future_to_job = {
            executor.submit(monitor_and_download_job, job_info): job_info 
            for job_info in jobs_to_monitor
        }
        
        # Collect results as they complete
        completed_count = 0
        for future in as_completed(future_to_job):
            completed_count += 1
            job_info = future_to_job[future]
            
            try:
                result = future.result()
                results.append(result)
                log_debug(f'Completed {completed_count}/{len(jobs_to_monitor)}: {job_info["name"]} -> {result["status"]}')
            except Exception as e:
                # Handle executor exceptions
                log_info(f'  ✗ Exception during monitoring for {job_info["name"]}: {e}')
                results.append({
                    'name': job_info['name'],
                    'status': 'MONITOR_EXCEPTION',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
    
    return results

# ========================================
# Functions for Backward Compatibility
# ========================================

def process_dashboard_backup(dashboard: Dict[str, Any], index: int, total: int, account_id: str) -> Dict[str, Any]:
    """
    Process backup of a single dashboard (for backward compatibility).
    
    Args:
        dashboard: Dashboard summary object
        index: Current dashboard index (1-based)
        total: Total number of dashboards
        account_id: AWS Account ID to use for this backup
        
    Returns:
        Backup result dictionary
    """
    # Extract dashboard information with safe defaults
    arn = dashboard.get('Arn', '')
    name = dashboard.get('Name', 'Unknown')
    
    # Validate required fields
    if not arn:
        log_info(f'[{index}/{total}] Processing: {name} - Missing ARN, skipping')
        return {
            'name': name,
            'status': 'MISSING_ARN',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    
    job_id = arn.split('/')[-1] if arn else f'job_{index}'
    
    log_info(f'[{index}/{total}] Processing: {name}')
    
    # Start export job
    export_response = start_asset_bundle_export_job(account_id, name, arn, job_id)
    
    if export_response is None:
        # Failed to start export job
        result = 'EXPORT_START_FAILED'
    else:
        # Wait a bit then check status
        time.sleep(1)
        # Monitor job status and download file if successful
        result = check_job_status_and_retry(job_id, name, account_id)
    
    return {
        'name': name,
        'status': result,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

# ========================================
# Main Processing Functions
# ========================================

def backup_all_dashboards(account_id: Optional[str] = None, max_workers: Optional[int] = None) -> None:
    """
    Main function to backup all dashboards from QuickSight account.
    
    Uses a two-phase approach for optimal performance:
    1. Start all export jobs simultaneously
    2. Monitor results and download concurrently using ThreadPoolExecutor
    
    Args:
        account_id: AWS Account ID (optional, uses global ACCOUNT_ID if not provided)
        max_workers: Maximum concurrent threads for monitoring/downloading (default: min(32, dashboard count))
    """
    # Initialize AWS resources if not already initialized
    _, _, _, resolved_account_id = initialize_aws_resources()
    
    # Use provided account_id or resolved ACCOUNT_ID
    target_account_id = account_id or resolved_account_id
    
    if not target_account_id:
        raise ValueError("No Account ID available. Either provide account_id parameter or ensure AWS credentials are available.")
    
    log_info(f'Starting QuickSight dashboard backup for account: {target_account_id}')
    
    # Clear previous backup results to avoid accumulation
    backup_results.clear()
    
    # Get list of all dashboards
    dashboards = get_dashboard_list(target_account_id)
    
    if not dashboards:
        log_info('No dashboards found to backup')
        return
    
    log_info(f'Found {len(dashboards)} dashboards to backup')
    
    # ===========================================
    # Phase 1: Start export jobs with limited concurrency
    # ===========================================
    jobs_to_monitor, failed_starts = execute_phase_1_start_jobs(dashboards, target_account_id)
    
    # Add failed starts to results immediately
    backup_results.extend(failed_starts)
    
    if not jobs_to_monitor:
        log_info('No export jobs started successfully. Backup complete.')
        return
    
    log_info(f'Phase 1 complete: {len(jobs_to_monitor)} jobs started, {len(failed_starts)} failed to start')
    
    # ===========================================
    # Phase 2: Concurrent monitoring and downloading
    # ===========================================
    monitor_results = execute_phase_2_monitor_jobs(jobs_to_monitor, max_workers)
    backup_results.extend(monitor_results)
    
    log_info('Phase 2 complete: All jobs monitored and downloads attempted')

# ========================================
# Report Functionality
# ========================================

def generate_backup_report() -> None:
    """Generate and display comprehensive backup report."""
    log_info('\n' + '='*60)
    log_info('BACKUP REPORT')
    log_info('='*60)
    
    # Calculate statistics
    total_dashboards = len(backup_results)
    successful_backups = [r for r in backup_results if r['status'] == 'SUCCESS']
    failed_backups = [r for r in backup_results if r['status'] != 'SUCCESS']
    
    # Display summary
    log_info(f'Total dashboards: {total_dashboards}')
    log_info(f'Successful backups: {len(successful_backups)}')
    log_info(f'Failed backups: {len(failed_backups)}')
    
    # Display successful backups
    if successful_backups:
        log_info('\nSuccessful backups:')
        for result in successful_backups:
            log_info(f'  ✓ {result["name"]} ({result["timestamp"]})')
    
    # Display failed backups
    if failed_backups:
        log_info('\nFailed backups:')
        for result in failed_backups:
            log_info(f'  ✗ {result["name"]} - {result["status"]} ({result["timestamp"]})')
    
    # Display backup location
    if S3_BUCKET_NAME:
        log_info(f'\nBackup files saved to: s3://{S3_BUCKET_NAME}/')
    else:
        log_info(f'\nBackup files saved to: {os.path.abspath(BACKUP_DIR)}')
    log_info('='*60)

# ========================================
# Entry Points
# ========================================

def lambda_handler(event=None, context=None) -> Dict[str, Any]:
    """
    AWS Lambda entry point.
    
    Args:
        event: Lambda event object (unused)
        context: Lambda context object (unused)
        
    Returns:
        Lambda response dictionary
    """
    # Suppress unused parameter warnings
    _ = event
    _ = context
    
    start_time = datetime.now()
    
    try:
        # Execute backup process (auto-detect if ACCOUNT_ID not set)
        backup_all_dashboards()
        
        # Calculate execution time
        end_time = datetime.now()
        duration = end_time - start_time
        
        log_info(f'\nBackup completed in {duration.total_seconds():.1f} seconds')
        generate_backup_report()
        
        # Return success response
        return {
            'statusCode': 200,
            'body': {
                'account_id': ACCOUNT_ID,
                'total': len(backup_results),
                'successful': len([r for r in backup_results if r['status'] == 'SUCCESS']),
                'failed': len([r for r in backup_results if r['status'] != 'SUCCESS']),
                'duration': duration.total_seconds()
            }
        }
        
    except Exception as e:
        log_info(f'Error during backup process: {e}')
        return {
            'statusCode': 500,
            'body': {
                'error': str(e)
            }
        }

def main() -> None:
    """
    Main entry point for standalone execution.
    """
    start_time = datetime.now()
    
    try:
        # Execute backup process (auto-detect if ACCOUNT_ID not set)
        backup_all_dashboards()
        
        # Calculate execution time and generate report
        end_time = datetime.now()
        duration = end_time - start_time
        
        log_info(f'\nBackup completed in {duration.total_seconds():.1f} seconds')
        generate_backup_report()
        
    except Exception as e:
        log_info(f'Error during backup process: {e}')
        raise

# ========================================
# Script Execution
# ========================================

if __name__ == "__main__":
    main()