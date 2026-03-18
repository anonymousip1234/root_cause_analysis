#!/usr/bin/env bash
#
# AIQE RCA Engine — Deploy to a free-tier EC2 t2.micro instance.
#
# What this script does:
#   1. Creates a security group (HTTP 80 + SSH 22)
#   2. Creates a key pair (for SSH access)
#   3. Launches a t2.micro instance with Docker + Docker Compose pre-installed
#   4. Clones your repo and runs docker compose up
#
# Prerequisites:
#   - AWS CLI configured (aws configure)
#   - Git repo pushed to a remote (GitHub) — OR you can SCP the code manually
#
# Usage:
#   ./deploy/deploy-ec2.sh                        # defaults: us-east-1
#   ./deploy/deploy-ec2.sh us-east-1 my-repo-url  # custom region + repo
#
set -euo pipefail

REGION="${1:-us-east-1}"
REPO_URL="${2:-}"
APP_NAME="aiqe-rca"
KEY_NAME="${APP_NAME}-key"
SG_NAME="${APP_NAME}-sg"
INSTANCE_TYPE="t2.micro"

echo "==> Region: ${REGION}"

# ── Step 1: Get default VPC ──
echo "==> Finding default VPC..."
VPC_ID=$(aws ec2 describe-vpcs \
  --filters Name=is-default,Values=true \
  --query "Vpcs[0].VpcId" \
  --output text \
  --region "${REGION}")

if [ "${VPC_ID}" = "None" ] || [ -z "${VPC_ID}" ]; then
  echo "ERROR: No default VPC found in ${REGION}. Create one or pass a VPC ID."
  exit 1
fi
echo "    VPC: ${VPC_ID}"

# ── Step 2: Create key pair (skip if exists) ──
KEY_FILE="${HOME}/.ssh/${KEY_NAME}.pem"
if aws ec2 describe-key-pairs --key-names "${KEY_NAME}" --region "${REGION}" &>/dev/null; then
  echo "==> Key pair '${KEY_NAME}' already exists."
else
  echo "==> Creating key pair '${KEY_NAME}'..."
  mkdir -p "${HOME}/.ssh"
  aws ec2 create-key-pair \
    --key-name "${KEY_NAME}" \
    --query "KeyMaterial" \
    --output text \
    --region "${REGION}" > "${KEY_FILE}"
  chmod 400 "${KEY_FILE}"
  echo "    Saved to: ${KEY_FILE}"
fi

# ── Step 3: Create security group (skip if exists) ──
SG_ID=$(aws ec2 describe-security-groups \
  --filters Name=group-name,Values="${SG_NAME}" Name=vpc-id,Values="${VPC_ID}" \
  --query "SecurityGroups[0].GroupId" \
  --output text \
  --region "${REGION}" 2>/dev/null || echo "None")

if [ "${SG_ID}" = "None" ] || [ -z "${SG_ID}" ]; then
  echo "==> Creating security group '${SG_NAME}'..."
  SG_ID=$(aws ec2 create-security-group \
    --group-name "${SG_NAME}" \
    --description "AIQE RCA - HTTP + SSH" \
    --vpc-id "${VPC_ID}" \
    --query "GroupId" \
    --output text \
    --region "${REGION}")

  # Allow SSH (port 22)
  aws ec2 authorize-security-group-ingress \
    --group-id "${SG_ID}" \
    --protocol tcp --port 22 --cidr 0.0.0.0/0 \
    --region "${REGION}"

  # Allow HTTP (port 80)
  aws ec2 authorize-security-group-ingress \
    --group-id "${SG_ID}" \
    --protocol tcp --port 80 --cidr 0.0.0.0/0 \
    --region "${REGION}"

  echo "    Security group: ${SG_ID}"
else
  echo "==> Security group '${SG_NAME}' already exists: ${SG_ID}"
fi

# ── Step 4: Find latest Amazon Linux 2023 AMI ──
echo "==> Finding latest Amazon Linux 2023 AMI..."
AMI_ID=$(aws ec2 describe-images \
  --owners amazon \
  --filters \
    "Name=name,Values=al2023-ami-2023.*-x86_64" \
    "Name=state,Values=available" \
  --query "sort_by(Images, &CreationDate)[-1].ImageId" \
  --output text \
  --region "${REGION}")
echo "    AMI: ${AMI_ID}"

# ── Step 5: Build user-data script ──
# This runs on first boot to install Docker, clone repo, and start the app.
USER_DATA=$(cat <<'USERDATA'
#!/bin/bash
set -ex

# Create 4GB swap (t2.micro only has 1GB RAM, PyTorch needs more)
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile swap swap defaults 0 0' >> /etc/fstab

# Install Docker
dnf update -y
dnf install -y docker git
systemctl enable docker
systemctl start docker

# Install Docker Compose plugin
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Create app directory
mkdir -p /opt/aiqe-rca
cd /opt/aiqe-rca

USERDATA
)

# If a repo URL is provided, clone it; otherwise we'll SCP later
if [ -n "${REPO_URL}" ]; then
  USER_DATA+="
# Clone the repository
git clone ${REPO_URL} .

# Build and start
docker compose up -d --build

echo 'AIQE RCA deployment complete' > /opt/aiqe-rca/deploy.log
"
else
  USER_DATA+="
echo 'Docker ready. Upload code with: scp -r -i ${KEY_FILE} ./ ec2-user@<PUBLIC_IP>:/opt/aiqe-rca/' > /opt/aiqe-rca/deploy.log
echo 'Then SSH in and run: cd /opt/aiqe-rca && sudo docker compose up -d --build' >> /opt/aiqe-rca/deploy.log
"
fi

# ── Step 6: Check for existing instance ──
EXISTING=$(aws ec2 describe-instances \
  --filters \
    "Name=tag:Name,Values=${APP_NAME}" \
    "Name=instance-state-name,Values=running,pending" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text \
  --region "${REGION}" 2>/dev/null || echo "None")

if [ "${EXISTING}" != "None" ] && [ -n "${EXISTING}" ]; then
  echo ""
  echo "==> An instance '${APP_NAME}' is already running: ${EXISTING}"
  PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "${EXISTING}" \
    --query "Reservations[0].Instances[0].PublicIpAddress" \
    --output text \
    --region "${REGION}")
  echo "    Public IP: ${PUBLIC_IP}"
  echo ""
  echo "To redeploy, SSH in and pull latest:"
  echo "  ssh -i ${KEY_FILE} ec2-user@${PUBLIC_IP}"
  echo "  cd /opt/aiqe-rca && sudo git pull && sudo docker compose up -d --build"
  exit 0
fi

# ── Step 7: Launch instance ──
echo "==> Launching t2.micro instance..."
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "${AMI_ID}" \
  --instance-type "${INSTANCE_TYPE}" \
  --key-name "${KEY_NAME}" \
  --security-group-ids "${SG_ID}" \
  --user-data "${USER_DATA}" \
  --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=20,VolumeType=gp3}" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${APP_NAME}}]" \
  --query "Instances[0].InstanceId" \
  --output text \
  --region "${REGION}")

echo "    Instance: ${INSTANCE_ID}"
echo "==> Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids "${INSTANCE_ID}" --region "${REGION}"

PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids "${INSTANCE_ID}" \
  --query "Reservations[0].Instances[0].PublicIpAddress" \
  --output text \
  --region "${REGION}")

echo ""
echo "============================================"
echo "  AIQE RCA — EC2 Deployment Complete"
echo "============================================"
echo ""
echo "  Instance ID : ${INSTANCE_ID}"
echo "  Public IP   : ${PUBLIC_IP}"
echo "  SSH Key     : ${KEY_FILE}"
echo ""
echo "  SSH access:"
echo "    ssh -i ${KEY_FILE} ec2-user@${PUBLIC_IP}"
echo ""

if [ -n "${REPO_URL}" ]; then
  echo "  The app is building now (takes 3-5 min on first boot)."
  echo "  Check progress:"
  echo "    ssh -i ${KEY_FILE} ec2-user@${PUBLIC_IP} 'sudo docker compose -f /opt/aiqe-rca/docker-compose.yml logs -f'"
  echo ""
  echo "  Once ready, test:"
  echo "    curl http://${PUBLIC_IP}/health"
else
  echo "  Docker is installing. Upload your code in ~2 min:"
  echo ""
  echo "    scp -i ${KEY_FILE} -r . ec2-user@${PUBLIC_IP}:/tmp/aiqe-rca"
  echo "    ssh -i ${KEY_FILE} ec2-user@${PUBLIC_IP} 'sudo mv /tmp/aiqe-rca /opt/aiqe-rca'"
  echo "    ssh -i ${KEY_FILE} ec2-user@${PUBLIC_IP} 'cd /opt/aiqe-rca && sudo docker compose up -d --build'"
  echo ""
  echo "  Then test:"
  echo "    curl http://${PUBLIC_IP}/health"
fi

echo ""
echo "  Full test:"
echo "    curl -X POST http://${PUBLIC_IP}/analyze \\"
echo "      -F 'problem_statement=Bond failures on Line 2' \\"
echo "      -F 'files=@docs/Test01_LabTestReport.docx' \\"
echo "      -F 'output_format=pdf' -o report.pdf"
echo ""
echo "  IMPORTANT: Stop the instance when not testing to stay within free tier:"
echo "    aws ec2 stop-instances --instance-ids ${INSTANCE_ID} --region ${REGION}"
echo "    aws ec2 start-instances --instance-ids ${INSTANCE_ID} --region ${REGION}"
echo ""
