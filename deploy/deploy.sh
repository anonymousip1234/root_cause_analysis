#!/usr/bin/env bash
#
# AIQE RCA Engine — Build, push, and deploy to AWS ECS Fargate.
#
# Prerequisites:
#   - AWS CLI configured (aws configure)
#   - Docker running
#
# Usage:
#   ./deploy/deploy.sh                          # uses defaults
#   ./deploy/deploy.sh us-west-2 my-vpc-id subnet-a,subnet-b
#
set -euo pipefail

REGION="${1:-us-east-1}"
VPC_ID="${2:-}"
SUBNET_IDS="${3:-}"
APP_NAME="aiqe-rca"
STACK_NAME="${APP_NAME}-stack"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${APP_NAME}"

echo "==> Account: ${ACCOUNT_ID}, Region: ${REGION}"

# ── Step 1: Create ECR repo (if it doesn't exist) ──
echo "==> Creating ECR repository..."
aws ecr describe-repositories --repository-names "${APP_NAME}" --region "${REGION}" 2>/dev/null || \
  aws ecr create-repository --repository-name "${APP_NAME}" --region "${REGION}"

# ── Step 2: Build Docker image ──
echo "==> Building Docker image..."
docker build -t "${APP_NAME}:latest" .

# ── Step 3: Push to ECR ──
echo "==> Logging into ECR..."
aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "==> Tagging and pushing image..."
docker tag "${APP_NAME}:latest" "${ECR_REPO}:latest"
docker push "${ECR_REPO}:latest"

# ── Step 4: Deploy CloudFormation stack ──
if [ -z "${VPC_ID}" ] || [ -z "${SUBNET_IDS}" ]; then
  echo ""
  echo "==> Image pushed to: ${ECR_REPO}:latest"
  echo ""
  echo "To deploy the stack, provide VPC and subnet IDs:"
  echo "  ./deploy/deploy.sh ${REGION} <vpc-id> <subnet-id-1>,<subnet-id-2>"
  echo ""
  echo "Or deploy manually:"
  echo "  aws cloudformation deploy \\"
  echo "    --template-file deploy/cloudformation.yml \\"
  echo "    --stack-name ${STACK_NAME} \\"
  echo "    --capabilities CAPABILITY_NAMED_IAM \\"
  echo "    --parameter-overrides \\"
  echo "      ImageUri=${ECR_REPO}:latest \\"
  echo "      VpcId=<your-vpc-id> \\"
  echo "      SubnetIds=<subnet-1>,<subnet-2> \\"
  echo "    --region ${REGION}"
  exit 0
fi

echo "==> Deploying CloudFormation stack: ${STACK_NAME}..."
aws cloudformation deploy \
  --template-file deploy/cloudformation.yml \
  --stack-name "${STACK_NAME}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ImageUri="${ECR_REPO}:latest" \
    VpcId="${VPC_ID}" \
    SubnetIds="${SUBNET_IDS}" \
  --region "${REGION}"

# ── Step 5: Print output ──
echo ""
echo "==> Deployment complete!"
ALB_URL=$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs[?OutputKey=='ALBURL'].OutputValue" \
  --output text \
  --region "${REGION}")
echo "==> Application URL: ${ALB_URL}"
echo ""
echo "Test with:"
echo "  curl -X POST ${ALB_URL}/analyze \\"
echo "    -F 'problem_statement=Your problem here' \\"
echo "    -F 'files=@your_report.docx' \\"
echo "    -F 'output_format=pdf' -o report.pdf"
