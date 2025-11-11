"""AWS Spot Instance autoscaler for ClearML agents."""

import boto3
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from clearml.backend_api.session.client import APIClient


@dataclass
class AutoscalerConfig:
    """Configuration for Spot instance autoscaler."""
    region: str = "us-east-1"
    instance_type: str = "g4dn.xlarge"
    ami_id: str = "ami-0c55b159cbfafe1f0"
    key_name: str = "mlops-key"
    security_group_ids: List[str] = None
    subnet_id: str = ""
    queue_name: str = "default"
    min_instances: int = 0
    max_instances: int = 5
    scale_up_threshold: int = 2  # Tasks in queue
    scale_down_idle_time: int = 600  # Seconds
    check_interval: int = 60  # Seconds


class SpotInstanceAutoscaler:
    """Autoscaler for ClearML agents on AWS Spot instances."""

    def __init__(self, config: AutoscalerConfig, clearml_api_key: str):
        self.config = config
        self.ec2_client = boto3.client('ec2', region_name=config.region)
        self.clearml_client = APIClient()
        self.running_instances: Dict[str, Dict] = {}

    def get_queue_length(self, queue_name: str) -> int:
        """
        Get number of pending tasks in ClearML queue.

        Args:
            queue_name: ClearML queue name

        Returns:
            Number of pending tasks
        """
        try:
            # Query ClearML API for queue status
            queues = self.clearml_client.queues.get_all()
            for queue in queues:
                if queue.name == queue_name:
                    return queue.entries  # Number of pending tasks
        except Exception as e:
            print(f"Error getting queue length: {e}")
        return 0

    def get_running_agents(self, queue_name: str) -> int:
        """
        Get number of active ClearML agents.

        Args:
            queue_name: ClearML queue name

        Returns:
            Number of active agents
        """
        try:
            workers = self.clearml_client.workers.get_all()
            active_workers = [
                w for w in workers
                if w.queue == queue_name and w.is_alive
            ]
            return len(active_workers)
        except Exception as e:
            print(f"Error getting agents: {e}")
        return 0

    def launch_spot_instance(self) -> Optional[str]:
        """
        Launch a new Spot instance with ClearML agent.

        Returns:
            Instance ID if successful, None otherwise
        """
        user_data = f"""#!/bin/bash
apt-get update
apt-get install -y python3-pip docker.io
pip3 install clearml-agent

# Configure ClearML agent
clearml-agent init --api-host https://api.clearml.example.com

# Start agent as daemon
clearml-agent daemon --queue {self.config.queue_name} --docker
"""

        try:
            response = self.ec2_client.request_spot_instances(
                InstanceCount=1,
                Type='one-time',
                LaunchSpecification={
                    'ImageId': self.config.ami_id,
                    'InstanceType': self.config.instance_type,
                    'KeyName': self.config.key_name,
                    'SecurityGroupIds': self.config.security_group_ids or [],
                    'SubnetId': self.config.subnet_id,
                    'UserData': user_data,
                    'IamInstanceProfile': {
                        'Name': 'clearml-agent-role'
                    },
                    'BlockDeviceMappings': [{
                        'DeviceName': '/dev/sda1',
                        'Ebs': {
                            'VolumeSize': 100,
                            'VolumeType': 'gp3',
                            'DeleteOnTermination': True
                        }
                    }],
                    'TagSpecifications': [{
                        'ResourceType': 'instance',
                        'Tags': [
                            {'Key': 'Name', 'Value': f'clearml-agent-{queue_name}'},
                            {'Key': 'ManagedBy', 'Value': 'spot-autoscaler'},
                            {'Key': 'Queue', 'Value': self.config.queue_name}
                        ]
                    }]
                }
            )

            spot_request_id = response['SpotInstanceRequests'][0]['SpotInstanceRequestId']
            print(f"Launched Spot request: {spot_request_id}")

            return spot_request_id

        except Exception as e:
            print(f"Error launching Spot instance: {e}")
            return None

    def terminate_idle_instances(self):
        """Terminate instances that have been idle for too long."""
        try:
            # Get all instances managed by autoscaler
            response = self.ec2_client.describe_instances(
                Filters=[
                    {'Name': 'tag:ManagedBy', 'Values': ['spot-autoscaler']},
                    {'Name': 'tag:Queue', 'Values': [self.config.queue_name]},
                    {'Name': 'instance-state-name', 'Values': ['running']}
                ]
            )

            instances_to_terminate = []

            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    instance_id = instance['InstanceId']
                    launch_time = instance['LaunchTime']

                    # Check if instance has been idle
                    idle_time = (time.time() - launch_time.timestamp())

                    # In production, check actual agent activity
                    if idle_time > self.config.scale_down_idle_time:
                        instances_to_terminate.append(instance_id)

            if instances_to_terminate:
                self.ec2_client.terminate_instances(
                    InstanceIds=instances_to_terminate
                )
                print(f"Terminated idle instances: {instances_to_terminate}")

        except Exception as e:
            print(f"Error terminating instances: {e}")

    def scale(self):
        """Main scaling logic."""
        queue_length = self.get_queue_length(self.config.queue_name)
        active_agents = self.get_running_agents(self.config.queue_name)

        print(f"Queue: {self.config.queue_name}")
        print(f"  Pending tasks: {queue_length}")
        print(f"  Active agents: {active_agents}")

        # Scale up if needed
        if queue_length >= self.config.scale_up_threshold:
            instances_needed = min(
                queue_length - active_agents,
                self.config.max_instances - active_agents
            )

            if instances_needed > 0:
                print(f"Scaling up: launching {instances_needed} instances")
                for _ in range(instances_needed):
                    self.launch_spot_instance()

        # Scale down if idle
        elif active_agents > self.config.min_instances:
            self.terminate_idle_instances()

    def run(self):
        """Run autoscaler loop."""
        print(f"Starting Spot Autoscaler for queue: {self.config.queue_name}")
        print(f"  Min instances: {self.config.min_instances}")
        print(f"  Max instances: {self.config.max_instances}")
        print(f"  Instance type: {self.config.instance_type}")

        while True:
            try:
                self.scale()
            except Exception as e:
                print(f"Error in autoscaler loop: {e}")

            time.sleep(self.config.check_interval)


if __name__ == "__main__":
    config = AutoscalerConfig(
        region="us-east-1",
        instance_type="g4dn.xlarge",
        queue_name="gpu-training",
        min_instances=0,
        max_instances=5,
        security_group_ids=["sg-0123456789abcdef0"],
        subnet_id="subnet-0123456789abcdef0"
    )

    autoscaler = SpotInstanceAutoscaler(
        config=config,
        clearml_api_key="your-api-key"
    )

    autoscaler.run()
