output "domain_endpoint" { value = aws_opensearch_domain.f1.endpoint }
output "domain_arn"      { value = aws_opensearch_domain.f1.arn }
output "kibana_endpoint" { value = aws_opensearch_domain.f1.dashboard_endpoint }
