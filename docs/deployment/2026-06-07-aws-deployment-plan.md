# JAWAS — AWS Deployment Plan

> **Goal**: Deploy the full JAWAS stack on AWS at minimum cost (free for the first 12 months, ~$8/month after).
> Personal project, single-user, no high-availability requirements.

---

## Cost estimate

| Service | Free Tier (12 months) | After free tier |
|---|---|---|
| EC2 t3.micro | 750 h/month free | ~$8/month |
| PostgreSQL (Docker on EC2, not RDS) | Free (runs on EC2) | Free |
| SQS (3 queues) | 1 M requests/month free | ~$0 (personal use) |
| **Total** | **$0/month** | **~$8/month** |

> **Why not RDS?** RDS has a free tier too, but only for 12 months. Running Postgres inside
> the same EC2 is free indefinitely and perfectly fine for a personal project.

---

## Architecture

```
Your Mac (SSH) ──────► EC2 t3.micro (Ubuntu, 1 vCPU, 1 GB RAM)
                            │
                            │  Docker Compose (production)
                            ├── postgres:16   (container)
                            ├── fetcher
                            ├── enricher
                            ├── bot
                            └── publisher-x
                                   │
                                   ▼
                            AWS SQS (managed service)
                            ├── raw-items
                            ├── approved-drafts
                            └── dlq
```

---

## Phase A — AWS account setup (one-time)

### A.1 Create account

Go to [aws.amazon.com](https://aws.amazon.com) → Create account.
A credit card is required but **you will not be charged as long as you stay within the free tier**.

### A.2 Enable billing alert (mandatory)

This notifies you before any unexpected charge.

```
AWS Console → Billing → Budgets → Create budget
→ "Zero spend budget"  ← alerts on any spend at all
```

---

## Phase B — IAM: permissions

> **What is IAM**: Identity and Access Management. In AWS you never use the root account
> for day-to-day operations — you create users/roles with scoped permissions, just like
> creating a limited OS user instead of using root.

### B.1 Create IAM user for the app (SQS access)

```
Console → IAM → Users → Create user
Name: jawas-app
Access type: ✅ Programmatic access  (generates Access Key + Secret)
```

Create a custom inline policy (least privilege — only the SQS actions the app actually needs):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:us-east-1:*:*"
    }
  ]
}
```

Save the **Access Key ID** and **Secret Access Key** — you will need them in the server `.env`.

---

## Phase C — SQS: create queues

> **What is SQS**: Simple Queue Service. A managed message queue. In development you used
> LocalStack to emulate it locally. In production you use the real AWS SQS.

```
Console → SQS → Create queue
```

Create these 3 queues (type: **Standard**, not FIFO):

| Name | Special config |
|---|---|
| `raw-items` | Defaults |
| `approved-drafts` | Defaults |
| `dlq` | Defaults |

After creating each queue, copy its **Queue URL** — it looks like:

```
https://sqs.us-east-1.amazonaws.com/123456789012/raw-items
```

Connect the DLQ to the other queues *(optional but recommended)*:

```
raw-items → Edit → Dead-letter queue → dlq, Max receives: 3
approved-drafts → Edit → Dead-letter queue → dlq, Max receives: 3
```

---

## Phase D — EC2: launch the server

> **What is EC2**: Elastic Compute Cloud. Essentially a VM in the cloud.
> t3.micro is the smallest free-tier option: 1 vCPU, 1 GB RAM.

### D.1 Launch instance

```
Console → EC2 → Launch Instance
```

| Field | Value |
|---|---|
| Name | jawas-server |
| AMI | Ubuntu Server 24.04 LTS (64-bit x86) |
| Instance type | t3.micro (Free tier eligible) |
| Key pair | Create new: `jawas-key`, RSA, .pem format |
| Storage | 20 GB gp3 (default) |

### D.2 Security Group (AWS firewall)

> **What is a Security Group**: The firewall for your EC2 instance. Defines what traffic is
> allowed in and out. We only open SSH, and only from your IP.

```
Security group:
  Inbound rules:
    - SSH (port 22) → My IP  (AWS fills in your current IP automatically)

  Outbound rules:
    - All traffic → 0.0.0.0/0  (leave as default — the server needs to reach the internet)
```

> The app has no HTTP API, so no web ports need to be opened.

### D.3 Connect via SSH

Once the instance shows `Running`:

```bash
# On your Mac — fix key file permissions first
chmod 400 ~/Downloads/jawas-key.pem

# Get the Public IPv4 DNS from Console → EC2 → your instance
ssh -i ~/Downloads/jawas-key.pem ubuntu@<your-public-dns>

# Example:
ssh -i ~/Downloads/jawas-key.pem ubuntu@ec2-54-123-45-67.compute-1.amazonaws.com
```

---

## Phase E — Server setup

Run these commands inside the EC2 (connected via SSH):

### E.1 Install Docker

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker (official script)
curl -fsSL https://get.docker.com | sudo sh

# Add your user to the docker group (avoid typing sudo every time)
sudo usermod -aG docker ubuntu

# Activate the new group (or reconnect via SSH)
newgrp docker

# Verify
docker --version
docker compose version
```

### E.2 Clone the repo

```bash
sudo apt install -y git

git clone https://github.com/<your-username>/jawas.git
cd jawas
```

---

## Phase F — Production docker-compose

Create `docker-compose.prod.yml` in the repo root (on your Mac, then `git push`):

```yaml
# docker-compose.prod.yml — production: no localstack, internal postgres
version: "3.9"

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: jawas
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: jawas
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped
    # No "ports:" — postgres is not exposed to the internet

  fetcher:
    build: .
    command: python -m src.fetcher.main
    env_file: .env
    depends_on: [postgres]
    restart: unless-stopped

  enricher:
    build: .
    command: python -m src.enricher.main
    env_file: .env
    depends_on: [postgres]
    restart: unless-stopped

  bot:
    build: .
    command: python -m src.bot.main
    env_file: .env
    depends_on: [postgres]
    restart: unless-stopped

  publisher-x:
    build: .
    command: python -m src.publisher.main x
    env_file: .env
    depends_on: [postgres]
    restart: unless-stopped

volumes:
  postgres_data:
```

> **Changes vs dev `docker-compose.yml`**:
> - No `localstack` service
> - No `ports: 5432:5432` on postgres
> - `restart: unless-stopped` on all services (auto-restart on crash or server reboot)
> - `POSTGRES_PASSWORD` comes from `.env` (not hardcoded)

---

## Phase G — Production .env

On the EC2, inside the `jawas/` directory:

```bash
nano .env
```

```bash
# Database — points to the internal postgres container
DATABASE_URL=postgresql://jawas:<POSTGRES_PASSWORD>@postgres:5432/jawas

# AWS — credentials for the IAM user "jawas-app"
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<your-access-key-id>
AWS_SECRET_ACCESS_KEY=<your-secret-access-key>
# SQS_ENDPOINT_URL must be absent or empty so boto3 uses real AWS SQS
# SQS_ENDPOINT_URL=   ← do NOT set this

# Real SQS URLs (copied when you created the queues)
RAW_ITEMS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/raw-items
APPROVED_DRAFTS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/approved-drafts
DLQ_URL=https://sqs.us-east-1.amazonaws.com/123456789012/dlq

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
RELEVANCE_THRESHOLD=7

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ADMIN_CHAT_ID=...

# X (Twitter)
X_CONSUMER_KEY=...
X_CONSUMER_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...

# Jina AI
JINA_API_KEY=...

# Reddit (optional — leave blank to skip)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=jawas/1.0

# Fetcher config
FETCH_INTERVAL_HOURS=2
X_PROFILES=sama,karpathy,ylecun
HN_KEYWORDS=AI,LLM,Claude,GPT,machine learning,anthropic,openai
REDDIT_SUBREDDITS=MachineLearning,artificial,LocalLLaMA

# Used by docker-compose.prod.yml
POSTGRES_PASSWORD=<generate-a-strong-password>
```

> **Security**: This file is gitignored and lives only on the server. Never commit it.

---

## Phase H — First deploy

```bash
# Inside the EC2, in ~/jawas/

# 1. Build images (takes ~5 min on first run — downloads Playwright/Chromium)
docker compose -f docker-compose.prod.yml build

# 2. Start postgres first
docker compose -f docker-compose.prod.yml up -d postgres

# 3. Wait and run migrations
sleep 5
docker compose -f docker-compose.prod.yml run --rm fetcher poetry run alembic upgrade head

# 4. Start all services
docker compose -f docker-compose.prod.yml up -d

# 5. Tail logs
docker compose -f docker-compose.prod.yml logs -f

# 6. Check container status
docker compose -f docker-compose.prod.yml ps
```

All 5 containers should show `Up`.

---

## Phase I — Auto-restart on server reboot

`restart: unless-stopped` in docker-compose handles container crashes.
To make Docker itself start on EC2 reboot:

```bash
# Enable Docker on boot
sudo systemctl enable docker

# Create a systemd service for the compose stack
sudo nano /etc/systemd/system/jawas.service
```

```ini
[Unit]
Description=JAWAS Agent
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/jawas
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
User=ubuntu

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable jawas
sudo systemctl start jawas
```

---

## Phase J — Update workflow

When you push code changes:

```bash
# On your Mac
git push origin feat/phase-1-foundation

# On the EC2
cd ~/jawas
git pull
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

---

## Memory warning (important)

The EC2 t3.micro has **1 GB of RAM**. Playwright/Chromium (used by the fetcher for X profile
scraping) can consume ~400 MB when active. This is tight.

**If the server runs out of memory (OOM), options in order of cost:**

### Option 1 — Add swap (free, recommended regardless)

```bash
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Option 2 — Disable X scraping

Set `X_PROFILES=` (empty) in `.env`. The X profile scraping is the only component that uses
Playwright/Chromium. Disabling it drops peak memory significantly.

### Option 3 — Upgrade to t3.small

2 GB RAM, ~$15/month. Resolves the problem permanently.

---

## AWS concepts learned in this deployment

| AWS concept | Where you use it |
|---|---|
| IAM Users and Policies | Scoped SQS access for the app |
| Security Groups | EC2 firewall — SSH only from your IP |
| SQS Standard Queues | Real message queues replacing LocalStack |
| EC2 Free Tier | The server running all containers |
| SSH key pairs | Connecting to the server |
| systemd | Auto-start the app on EC2 reboot |
