output "public_ip"      { value = aws_eip.elk.public_ip }
output "kibana_url"     { value = "http://${aws_eip.elk.public_ip}:5601" }
output "logstash_url"   { value = "http://${aws_eip.elk.public_ip}:8080" }
output "instance_id"    { value = aws_instance.elk.id }
