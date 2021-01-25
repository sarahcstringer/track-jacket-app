resource "aws_security_group" "basic" {
  name = "basic"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

}
resource "aws_key_pair" "deployer" {
  key_name   = "keypair"
  public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCslPy5xQdudfReZoVxiepr5D1VFye9hpWU6Ny3ZLySG/ezyO5U21vaY/quuGvaIMnakjcCEcrmqXAd088ji5zvMX2/V0bJ8Gi3S7h/b7NXEslSITazAMWSAqJwuLb1nAzzZFeZsHF9s7GHi/3Tf9XF0vaxDg4cvLivqQ2OYjDoCpzwA1yxV03/hbINQ+ebDSU7WV5VlBNcfRcaVDz3hXjkOEHdWSp644A/C2qVazP4H37+Y7Xhxs6LZ7+bGsZH7UeUK+1X7Mq5/AUXkApZ2LVbL8lrZZk7zCtjTd/4IPuZaFwpvn3XHyH1uj7ay8MErDbFOo1NocR39mBZ6/E+iHVv"
}


data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-xenial-16.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical
}


resource "aws_instance" "server" {
  ami             = data.aws_ami.ubuntu.id
  instance_type   = "t2.micro"
  key_name        = aws_key_pair.deployer.key_name
  user_data       = file("install.sh")
  security_groups = [aws_security_group.basic.name]
}


