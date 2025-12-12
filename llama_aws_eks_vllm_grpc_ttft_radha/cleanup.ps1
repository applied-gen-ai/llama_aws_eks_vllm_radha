Write-Host " Cleaning up Kubernetes workloads..."

# Core workloads
kubectl delete all --all --ignore-not-found
kubectl delete svc --all --ignore-not-found
kubectl delete configmap --all --ignore-not-found
kubectl delete secrets --all --ignore-not-found

# HPA cleanup
Write-Host "`n Deleting Horizontal Pod Autoscalers..."
kubectl delete hpa --all --ignore-not-found


Write-Host "`n Destroying EKS Node Group (module.eks)..."
terraform destroy -target "module.eks.aws_eks_node_group.llm_nodes" -auto-approve

Write-Host "`n Destroying EKS Cluster (module.eks)..."
terraform destroy -target "module.eks.aws_eks_cluster.llm_cluster" -auto-approve

Write-Host "`n Final sweep: Destroying any remaining infra..."
terraform destroy -auto-approve

Write-Host "`n Cleanup complete! Check the AWS console. Peace out, infra!"
