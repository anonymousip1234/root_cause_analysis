param(
    [string]$Region = "us-east-1",
    [string]$VpcId = "",
    [string]$SubnetIds = ""
)

$ErrorActionPreference = "Stop"

# Load local .env values into this process so aws/docker commands can use them.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') {
            return
        }

        $parts = $_ -split '=', 2
        if ($parts.Count -eq 2) {
            $name = $parts[0].Trim()
            $value = $parts[1].Trim().Trim('"')
            [System.Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
}

$AppName = "aiqe-rca"
$StackName = "$AppName-stack"

$AccountId = aws sts get-caller-identity --query Account --output text
if (-not $AccountId) {
    throw "Unable to determine AWS account ID. Run 'aws configure' first."
}

$EcrRegistry = "$AccountId.dkr.ecr.$Region.amazonaws.com"
$EcrRepo = "$EcrRegistry/$AppName"

Write-Host "==> Account: $AccountId, Region: $Region"

Write-Host "==> Creating ECR repository..."
$previousNativePreference = $PSNativeCommandUseErrorActionPreference
$PSNativeCommandUseErrorActionPreference = $false
aws ecr describe-repositories --repository-names $AppName --region $Region *> $null
$describeExitCode = $LASTEXITCODE
$PSNativeCommandUseErrorActionPreference = $previousNativePreference
if ($describeExitCode -ne 0) {
    aws ecr create-repository --repository-name $AppName --region $Region | Out-Null
}

Write-Host "==> Building Docker image..."
docker build -t "${AppName}:latest" .

Write-Host "==> Logging into ECR..."
$Password = aws ecr get-login-password --region $Region
$Password | docker login --username AWS --password-stdin $EcrRegistry

Write-Host "==> Tagging and pushing image..."
docker tag "${AppName}:latest" "${EcrRepo}:latest"
docker push "${EcrRepo}:latest"

if (-not $VpcId -or -not $SubnetIds) {
    Write-Host ""
    Write-Host "==> Image pushed to: ${EcrRepo}:latest"
    Write-Host ""
    Write-Host "To deploy the stack, provide VPC and subnet IDs:"
    Write-Host "  .\deploy\deploy.ps1 -Region $Region -VpcId <vpc-id> -SubnetIds <subnet-1,subnet-2>"
    Write-Host ""
    Write-Host "Or deploy manually:"
    Write-Host "  aws cloudformation deploy --template-file deploy/cloudformation.yml --stack-name $StackName --capabilities CAPABILITY_NAMED_IAM --parameter-overrides ImageUri=${EcrRepo}:latest VpcId=<your-vpc-id> SubnetIds=<subnet-1>,<subnet-2> --region $Region"
    exit 0
}

Write-Host "==> Deploying CloudFormation stack: $StackName..."
aws cloudformation deploy `
    --template-file deploy/cloudformation.yml `
    --stack-name $StackName `
    --capabilities CAPABILITY_NAMED_IAM `
    --parameter-overrides `
        "ImageUri=${EcrRepo}:latest" `
        "VpcId=$VpcId" `
        "SubnetIds=$SubnetIds" `
    --region $Region

Write-Host ""
Write-Host "==> Deployment complete!"
$AlbUrl = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --query "Stacks[0].Outputs[?OutputKey=='ALBURL'].OutputValue" `
    --output text `
    --region $Region
Write-Host "==> Application URL: $AlbUrl"
Write-Host ""
Write-Host "Test with:"
Write-Host "  curl -X POST ${AlbUrl}/analyze -F 'problem_statement=Your problem here' -F 'files=@your_report.docx' -F 'output_format=pdf' -o report.pdf"
