output "instance_ip_addr" {
  value = aws_instance.server.public_ip
}

output "aws_eip" {
  value = aws_eip.eip.public_ip
}
