"""Provision the authorized Lerny worker. No inbound ports; no credentials in user data."""
import argparse
import base64
import json
import time
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ROLE = "LernyWorkerRole"
PROFILE = "LernyWorkerProfile"
TAGS = [{"Key": "Project", "Value": "Lerny"}, {"Key": "ManagedBy", "Value": "lerny-deploy"}]

BOOTSTRAP = """#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends docker.io python3-venv python3-pip python3-boto3 ca-certificates curl unzip
systemctl enable --now docker
useradd --system --create-home --home-dir /var/lib/lerny-worker --shell /usr/sbin/nologin lerny-worker
useradd --system --create-home --home-dir /var/lib/lerny-code --shell /usr/sbin/nologin --groups docker lerny-code
install -d -m 0755 /opt/lerny/releases
install -d -m 0700 /etc/lerny
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
touch /var/lib/lerny-bootstrap-ready
"""


def managed(tags):
    return {x["Key"]: x["Value"] for x in tags or []}.get("ManagedBy") == "lerny-deploy"


def provision(args):
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    cfg = Config(connect_timeout=5, read_timeout=30, retries={"total_max_attempts": 3, "mode": "standard"})
    sts, ec2, iam, ssm, s3 = [session.client(name, config=cfg) for name in ("sts", "ec2", "iam", "ssm", "s3")]
    account = sts.get_caller_identity()["Account"]
    if account != args.account:
        raise ValueError("AWS_ACCOUNT_MISMATCH")
    ami = ssm.get_parameter(Name="/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id")["Parameter"]["Value"]
    image = ec2.describe_images(ImageIds=[ami])["Images"][0]
    if image["OwnerId"] != "099720109477" or image["Architecture"] != "x86_64":
        raise ValueError("AMI_OWNER_OR_ARCHITECTURE_MISMATCH")
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"]
    if len(vpcs) != 1:
        raise ValueError("ONE_DEFAULT_VPC_REQUIRED")
    vpc = vpcs[0]["VpcId"]
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc]},
                                          {"Name": "default-for-az", "Values": ["true"]}])["Subnets"]
    subnet = sorted(subnets, key=lambda x: x["AvailabilityZone"])[0]["SubnetId"]
    bucket = f"lerny-deploy-{account}-{args.region}"
    plan = {"account": account, "region": args.region, "ami": ami, "type": "t3.small",
            "disk_gb": 24, "cpu_credits": "standard", "inbound_ports": [], "bucket": bucket,
            "parameter": "/lerny/production/worker-env", "vpc": vpc, "subnet": subnet}
    if not args.apply:
        print(json.dumps(plan))
        return
    try:
        role = iam.get_role(RoleName=ROLE)["Role"]
        if not managed(role.get("Tags")):
            raise ValueError("EXISTING_ROLE_NOT_OWNED")
    except iam.exceptions.NoSuchEntityException:
        role = iam.create_role(RoleName=ROLE, Tags=TAGS, AssumeRolePolicyDocument=json.dumps({
            "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]
        }))["Role"]
    iam.attach_role_policy(RoleName=ROLE, PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore")
    iam.put_role_policy(RoleName=ROLE, PolicyName="LernyWorkerReleaseAndConfiguration", PolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/releases/*"},
            {"Effect": "Allow", "Action": "ssm:GetParameter", "Resource": f"arn:aws:ssm:{args.region}:{account}:parameter/lerny/production/worker-env"},
        ]}))
    try:
        profile = iam.get_instance_profile(InstanceProfileName=PROFILE)["InstanceProfile"]
        if not managed(profile.get("Tags")):
            raise ValueError("EXISTING_PROFILE_NOT_OWNED")
    except iam.exceptions.NoSuchEntityException:
        profile = iam.create_instance_profile(InstanceProfileName=PROFILE, Tags=TAGS)["InstanceProfile"]
    if not profile.get("Roles"):
        iam.add_role_to_instance_profile(InstanceProfileName=PROFILE, RoleName=ROLE)
    elif {r["RoleName"] for r in profile["Roles"]} != {ROLE}:
        raise ValueError("INSTANCE_PROFILE_ROLE_MISMATCH")
    try:
        s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=account)
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": args.region})
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={"Rules": [{
        "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})
    s3.put_bucket_tagging(Bucket=bucket, Tagging={"TagSet": TAGS})
    groups = ec2.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc]},
        {"Name": "group-name", "Values": ["lerny-worker-no-ingress"]}])["SecurityGroups"]
    if groups:
        if not managed(groups[0].get("Tags")) or groups[0]["IpPermissions"]:
            raise ValueError("EXISTING_SECURITY_GROUP_MISMATCH")
        group = groups[0]["GroupId"]
    else:
        group = ec2.create_security_group(GroupName="lerny-worker-no-ingress", VpcId=vpc,
            Description="Lerny worker: no inbound access, SSM administration only",
            TagSpecifications=[{"ResourceType": "security-group", "Tags": TAGS}])["GroupId"]
        ec2.revoke_security_group_egress(GroupId=group, IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
        ec2.authorize_security_group_egress(GroupId=group, IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": port, "ToPort": port,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": description}],
        } for port, description in ((80, "Signed OS package repositories"), (443, "AWS SSM and Storage APIs"), (6543, "Supabase TLS pooler"))])
    templates = ec2.describe_launch_templates(Filters=[{"Name": "launch-template-name", "Values": ["lerny-worker-20261110"]}])["LaunchTemplates"]
    if templates:
        if not managed(templates[0].get("Tags")):
            raise ValueError("EXISTING_TEMPLATE_NOT_OWNED")
        template_id = templates[0]["LaunchTemplateId"]
    else:
        template_id = ec2.create_launch_template(LaunchTemplateName="lerny-worker-20261110", VersionDescription="Ubuntu 24.04 isolated queue worker",
            TagSpecifications=[{"ResourceType": "launch-template", "Tags": TAGS}], LaunchTemplateData={
                "ImageId": ami, "InstanceType": "t3.small", "IamInstanceProfile": {"Name": PROFILE},
                "NetworkInterfaces": [{"DeviceIndex": 0, "SubnetId": subnet, "Groups": [group], "AssociatePublicIpAddress": True, "DeleteOnTermination": True}],
                "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1, "HttpEndpoint": "enabled"},
                "BlockDeviceMappings": [{"DeviceName": image["RootDeviceName"], "Ebs": {"VolumeSize": 24, "VolumeType": "gp3", "Encrypted": True, "DeleteOnTermination": True}}],
                "CreditSpecification": {"CpuCredits": "standard"}, "Monitoring": {"Enabled": False},
                "UserData": base64.b64encode(BOOTSTRAP.encode()).decode(),
                "TagSpecifications": [{"ResourceType": resource, "Tags": TAGS + [{"Key": "Name", "Value": "lerny-linux-worker"}]} for resource in ("instance", "volume")],
            })["LaunchTemplate"]["LaunchTemplateId"]
    existing = [i for p in ec2.get_paginator('describe_instances').paginate(Filters=[
        {"Name": "tag:Name", "Values": ["lerny-linux-worker"]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
    ]) for r in p["Reservations"] for i in r["Instances"]]
    if existing:
        if len(existing) != 1 or not managed(existing[0].get("Tags")):
            raise ValueError("EXISTING_INSTANCE_MISMATCH")
        instance = existing[0]["InstanceId"]
    else:
        # IAM profile propagation is eventually consistent.
        for attempt in range(6):
            try:
                response = ec2.run_instances(LaunchTemplate={"LaunchTemplateId": template_id, "Version": "1"},
                    MinCount=1, MaxCount=1, ClientToken="lerny-20261110-initial-worker")
                instance = response["Instances"][0]["InstanceId"]
                break
            except ClientError as error:
                if error.response["Error"]["Code"] != "InvalidParameterValue" or "instance profile" not in error.response["Error"].get("Message", "").lower() or attempt == 5:
                    raise
                time.sleep(5)
    plan.update(instance_id=instance, launch_template_id=template_id, security_group_id=group)
    Path(args.output).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(json.dumps(plan))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--apply", action="store_true")
    try:
        provision(parser.parse_args())
    except ClientError as error:
        print(json.dumps({"error": error.response["Error"]["Code"], "message": error.response["Error"].get("Message", "")[:300]}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
