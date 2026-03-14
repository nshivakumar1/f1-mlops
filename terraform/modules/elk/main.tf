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


resource "aws_iam_instance_profile" "elk" {
  name = "${var.project}-elk-profile"
  role = aws_iam_role.elk.name
}

# ── EC2 instance ───────────────────────────────────────────────────────────────

# SSH key pair — public key from developer's local ~/.ssh/id_rsa.pub
# Use EC2 Instance Connect as fallback: aws ec2-instance-connect send-ssh-public-key ...
resource "aws_key_pair" "elk" {
  key_name   = "${var.project}-elk-key"
  public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQDE2Fc4w7XpMogqNzEQDWxX+yAn4XcpxDt18SLkuE8FCKEjPXuWDI/WiUJkFZWw5NeWu29o7App/CwvwPAO5c0VvzXRib3aE4HCGRSzZ6XmFuVOM3Ae1OZ2QaritySd14m9hqSFpjdwaMktS/GyeneN2sITzMUqVhVNSNUKVY1SlmB86fvjzbLOIrbO8E8lhcygTSVRljwaa+xoqmIR/0zUBhFo4343nzEfYTqF8WSNxS/YGYOTc87YDZHIhKGaSNcsDmx2DxAwPao201bhhpHnI2sME8oi/Hv2Sm2ThHM49+48TnNs1omoqmWgenqtvGWAu1SNS+66wV/UMv/bUdB5NEh4xn1Mo8xsCnwH67IGC9gSZm+cJKGfTTrezV8m48J8DAzctPllBvBgShkS3fKogtKvhKWLA6I1m+m1Mt6fDVbzsMg1qNAqGu68aeDpLnHaO5zLK8QWtrzDVuT9KPwvlQkprhKztMQyk4zEL7tGpCgRppezUaD0W1hp6uxDovt2p0vl9PlNasG0yjnKRfKQBQ0ZC1xgtIYPIfMJJBn2ndS7LSj8ptHQaRbLULrk4r3+BU2G3twLnsBqvxtyBagTJYFDhHGAbwZbciaBSEg7jYuZI95Ik/CiFCi5PyldETR/338eueHBdcMoLKl7n5eIIu+S1pW9jkvKUZySibHrdw== nakulshivakumar@Nakuls-MacBook-Air.local"
}

resource "aws_instance" "elk" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = "t3.medium"
  key_name               = aws_key_pair.elk.key_name
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
