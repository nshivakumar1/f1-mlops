data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ── Security group ─────────────────────────────────────────────────────────────

resource "aws_security_group" "elk" {
  name        = "${var.project}-elk"
  description = "ELK stack: Kibana (5601), Logstash HTTP (8080), SSH (22)"

  ingress {
    description = "Kibana UI"
    from_port   = 5601
    to_port     = 5601
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Logstash HTTP input (Lambda direct push)"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-elk" }
}

# ── IAM role + instance profile (S3 read for Logstash) ────────────────────────

resource "aws_iam_role" "elk" {
  name = "${var.project}-elk-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "elk_s3" {
  name = "${var.project}-elk-s3-read"
  role = aws_iam_role.elk.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"]
      Resource = [
        "arn:aws:s3:::${var.s3_bucket}",
        "arn:aws:s3:::${var.s3_bucket}/*"
      ]
    }]
  })
}

# CloudWatch Logs + Metrics read — required by Logstash cloudwatch plugins
resource "aws_iam_role_policy" "elk_cloudwatch" {
  name = "${var.project}-elk-cloudwatch-read"
  role = aws_iam_role.elk.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams",
          "logs:FilterLogEvents",
          "logs:GetLogEvents",
          "logs:StartQuery",
          "logs:GetQueryResults",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricData",
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeTags",
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "elk" {
  name = "${var.project}-elk-profile"
  role = aws_iam_role.elk.name
}

# ── EC2 instance ───────────────────────────────────────────────────────────────

resource "aws_instance" "elk" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = "t3.medium"
  iam_instance_profile   = aws_iam_instance_profile.elk.name
  vpc_security_group_ids = [aws_security_group.elk.id]

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    tags        = { Name = "${var.project}-elk-root" }
  }

  user_data = templatefile("${path.module}/templates/elk_setup.sh.tpl", {
    s3_bucket  = var.s3_bucket
    aws_region = var.aws_region
    project    = var.project
  })

  tags = { Name = "${var.project}-elk" }
}

# ── Elastic IP (stable address for Lambda + Firehose endpoints) ───────────────

resource "aws_eip" "elk" {
  instance = aws_instance.elk.id
  domain   = "vpc"
  tags     = { Name = "${var.project}-elk-eip" }
}
