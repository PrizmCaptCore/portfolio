#!/bin/bash
set -e

# Log all output
exec > >(tee /var/log/userdata.log)
exec 2>&1

echo "Starting MLOps agent setup at $(date)"

# Update system
apt-get update
apt-get upgrade -y

# Install dependencies
apt-get install -y \
    python3-pip \
    python3-venv \
    docker.io \
    awscli \
    git \
    curl \
    vim \
    htop

# Start Docker service
systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
    -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Create working directory
mkdir -p /opt/mlops-agent
cd /opt/mlops-agent

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install MLOps agent dependencies
pip install \
    boto3 \
    requests \
    pyyaml \
    psutil

# Configure AWS CLI
mkdir -p /home/ubuntu/.aws
cat > /home/ubuntu/.aws/config <<EOF
[default]
region = us-west-2
output = json
EOF

chown -R ubuntu:ubuntu /home/ubuntu/.aws

# Configure MLOps agent
cat > /opt/mlops-agent/config.yaml <<EOF
server:
  url: "${agent_server_url}"
  access_key: "${agent_access_key}"
  secret_key: "${agent_secret_key}"

agent:
  name: "agent-$(hostname)"
  environment: "${environment}"
  max_workers: 4

logging:
  level: INFO
  file: /var/log/mlops-agent.log
EOF

# Create systemd service
cat > /etc/systemd/system/mlops-agent.service <<EOF
[Unit]
Description=MLOps Agent
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/mlops-agent
Environment="PATH=/opt/mlops-agent/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/mlops-agent/venv/bin/python3 -m mlops_agent.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Set permissions
chown -R ubuntu:ubuntu /opt/mlops-agent

# Enable and start service (commented out for demo)
# systemctl enable mlops-agent
# systemctl start mlops-agent

# Configure CloudWatch Logs
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<EOF
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/mlops-agent.log",
            "log_group_name": "/aws/ec2/mlops-agent-${environment}",
            "log_stream_name": "{instance_id}/agent"
          },
          {
            "file_path": "/var/log/userdata.log",
            "log_group_name": "/aws/ec2/mlops-agent-${environment}",
            "log_stream_name": "{instance_id}/userdata"
          }
        ]
      }
    }
  }
}
EOF

# Signal completion
touch /tmp/userdata_complete

echo "MLOps agent setup completed at $(date)"
