output "cluster_name" {
  description = "EKS cluster name"
  value       = aws_eks_cluster.llm_cluster.name
}

output "cluster_endpoint" {
  description = "EKS cluster endpoint"
  value       = aws_eks_cluster.llm_cluster.endpoint
}

output "cluster_certificate_authority" {
  description = "EKS cluster CA certificate"
  value       = data.aws_eks_cluster.eks.certificate_authority[0].data
}

output "cluster_token" {
  description = "EKS authentication token (sensitive)"
  value     = data.aws_eks_cluster_auth.eks.token
  sensitive = true
}

output "alb_controller_serviceaccount_role_arn" {
  description = "IAM Role ARN for AWS Load Balancer Controller Service Account"
  value       = aws_iam_role.alb_controller_role.arn
}
