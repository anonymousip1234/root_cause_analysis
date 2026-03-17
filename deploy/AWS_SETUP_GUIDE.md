# AWS Infrastructure Setup Guide

This guide walks through setting up the AWS infrastructure needed to deploy the AIQE RCA Engine.

**Account ID:** `993458096535`
**Region:** `us-east-1`

---

## Option A: One-Click CloudFormation (Recommended)

1. Log into the AWS Console
2. Go to **CloudFormation** → **Create Stack** → **With new resources**
3. Upload `deploy/cloudformation.yml`
4. Fill in parameters:
   - **ImageUri**: Will be set after first Docker push (use placeholder initially)
   - **VpcId**: Select your VPC
   - **SubnetIds**: Select 2 subnets in different AZs
5. Check "I acknowledge that AWS CloudFormation might create IAM resources with custom names"
6. Click **Create Stack**

This creates: ECR repo, ECS cluster, Fargate service, ALB, S3 bucket, IAM roles, security groups, CloudWatch logs.

---

## Option B: Manual Setup (Step by Step)

### Step 1: Create ECR Repository

```bash
aws ecr create-repository --repository-name aiqe-rca --region us-east-1
```

In Console: **ECR → Repositories → Create Repository** → Name: `aiqe-rca`

### Step 2: Create ECS Cluster

```bash
aws ecs create-cluster --cluster-name aiqe-rca-cluster --region us-east-1
```

In Console: **ECS → Clusters → Create Cluster**
- Name: `aiqe-rca-cluster`
- Infrastructure: **AWS Fargate**

### Step 3: Create Task Definition

In Console: **ECS → Task Definitions → Create new task definition**
- Family: `aiqe-rca`
- Launch type: **Fargate**
- CPU: `1 vCPU`, Memory: `2 GB`
- Container:
  - Name: `aiqe-rca`
  - Image: `993458096535.dkr.ecr.us-east-1.amazonaws.com/aiqe-rca:latest`
  - Port: `8000`
  - Environment variables:
    - `AWS_ACCESS_KEY_ID` = (your key)
    - `AWS_SECRET_ACCESS_KEY` = (your secret)
    - `AWS_REGION` = `us-east-1`
    - `AWS_S3_BUCKET` = `aiqe-bucket`

### Step 4: Create ALB + Target Group

In Console: **EC2 → Load Balancers → Create**
- Type: **Application Load Balancer**
- Name: `aiqe-rca-alb`
- Scheme: Internet-facing
- Listeners: HTTP port 80
- Select your VPC and 2 subnets
- Create a **Target Group**:
  - Type: IP
  - Port: 8000
  - Health check path: `/health`

### Step 5: Create ECS Service

In Console: **ECS → Clusters → aiqe-rca-cluster → Create Service**
- Launch type: **Fargate**
- Task definition: `aiqe-rca`
- Service name: `aiqe-rca-service`
- Desired tasks: `1`
- Networking: Select VPC, subnets, assign public IP
- Load balancing: Select the ALB and target group from Step 4

### Step 6: Create IAM User for CI/CD

In Console: **IAM → Users → Create User**
- Name: `aiqe-rca-deployer`
- Attach these policies:
  - `AmazonEC2ContainerRegistryPowerUser`
  - `AmazonECS_FullAccess`
- Create **Access Key** (CLI use case)
- Save the Access Key ID and Secret — these go into GitHub Secrets

---

## GitHub Secrets to Configure

Go to: **GitHub Repo → Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Value |
|-------------|-------|
| `AWS_ACCESS_KEY_ID` | Access key from CI/CD IAM user (Step 6) |
| `AWS_SECRET_ACCESS_KEY` | Secret key from CI/CD IAM user (Step 6) |

**Important:** Use the CI/CD deployer user's keys here, NOT the `s3-access` keys.

---

## After Setup: First Deploy

```bash
# macOS / Linux / Git Bash
./deploy/deploy.sh us-east-1 <vpc-id> <subnet-id-1>,<subnet-id-2>

# Windows PowerShell
.\deploy\deploy.ps1 -Region us-east-1 -VpcId <vpc-id> -SubnetIds <subnet-id-1>,<subnet-id-2>

# After that, every push to master auto-deploys via GitHub Actions
git push origin master
```

### Important Notes

- `deploy/deploy.sh` is a Bash script. It will not run in plain Windows PowerShell unless you use Git Bash, WSL, or similar.
- The deploy script only performs the full ECS deploy when you pass both `VpcId` and `SubnetIds`. If you run it with only `us-east-1`, it will stop after pushing the Docker image.
- Prerequisites for either script:
  - AWS CLI installed and configured (`aws configure`)
  - Docker Desktop installed and running
  - Two public subnets in the target VPC
- The CloudFormation stack injects `AWS_REGION` and `AWS_S3_BUCKET` into the container. S3 access is provided through the ECS task IAM role, so you do not need to hardcode AWS keys in the container when using the provided stack.

---

## Verify Deployment

1. **ECS Console** → Clusters → aiqe-rca-cluster → Services → check task is RUNNING
2. **EC2 Console** → Load Balancers → copy ALB DNS name
3. Test: `curl http://<alb-dns>/health`
