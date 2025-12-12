import subprocess
import json
import sys

# ============================================================
# Utility function to run shell commands safely
# ============================================================
def run_cmd(cmd, capture_output=True):
    """Run a shell command and return its output (or stream logs)."""
    print(f"\n  Running: {cmd}")
    result = subprocess.run(
        cmd, shell=True, capture_output=capture_output, text=True
    )
    if result.returncode != 0:
        print(f" Error while running: {cmd}")
        print(result.stderr)
        sys.exit(result.returncode)

    if capture_output:
        return result.stdout.strip()
    else:
        return ""


# ============================================================
# Step 1: Apply CRDs for AWS Load Balancer Controller
# ============================================================
def apply_crds():
    print("\n Applying CRDs for AWS Load Balancer Controller ...")
    cmd = (
        'kubectl apply -k '
        '"github.com/kubernetes-sigs/aws-load-balancer-controller/config/crd?ref=v2.8.3"'
    )
    run_cmd(cmd, capture_output=False)


# ============================================================
# Step 2: Add Helm repo and update
# ============================================================
def setup_helm_repo():
    print("\n Adding and updating Helm repository ...")
    run_cmd("helm repo add eks https://aws.github.io/eks-charts")
    run_cmd("helm repo update")


# ============================================================
# Step 3: Fetch cluster name, region, and VPC ID dynamically
# ============================================================
def get_cluster_info():
    print("\n Fetching cluster information ...")

    # Get all clusters safely as JSON
    clusters_json = run_cmd("aws eks list-clusters --output json")
    clusters = json.loads(clusters_json).get("clusters", [])

    if not clusters:
        print(" No EKS clusters found in your AWS account or region.")
        sys.exit(1)

    cluster_name = clusters[0]
    region = run_cmd("aws configure get region")

    # Fetch full cluster info as JSON
    cluster_desc_json = run_cmd(f"aws eks describe-cluster --name {cluster_name} --output json")
    cluster_desc = json.loads(cluster_desc_json)

    vpc_id = cluster_desc["cluster"]["resourcesVpcConfig"]["vpcId"]

    print(f" Cluster Name : {cluster_name}")
    print(f" Region       : {region}")
    print(f" VPC ID       : {vpc_id}")

    return cluster_name, region, vpc_id


# ============================================================
# Step 4: Confirm IRSA-linked ServiceAccount exists
# ============================================================
def verify_irsa_service_account():
    """Check that the ServiceAccount for the ALB Controller is annotated with the IRSA role ARN."""
    print("\n Verifying IRSA ServiceAccount annotation ...")
    cmd = "kubectl get sa aws-load-balancer-controller -n kube-system -o yaml"
    output = run_cmd(cmd)
    if "eks.amazonaws.com/role-arn" not in output:
        print(" No IRSA annotation found on ServiceAccount! Make sure Terraform created it correctly.")
        sys.exit(1)
    else:
        print(" IRSA ServiceAccount verified — annotation found.")


# ============================================================
# Step 5: Check if ALB Controller is already installed
# ============================================================
def controller_already_installed():
    """Check if the AWS Load Balancer Controller Helm release already exists."""
    print("\n Checking if AWS Load Balancer Controller is already installed ...")

    result = subprocess.run(
        "helm list -n kube-system -q",
        shell=True,
        capture_output=True,
        text=True
    )

    installed_releases = result.stdout.strip().splitlines()
    if "aws-load-balancer-controller" in installed_releases:
        print("ℹ  AWS Load Balancer Controller is already installed. It will be upgraded if needed.")
        return True
    else:
        print(" AWS Load Balancer Controller not found — proceeding with fresh installation.")
        return False


# ============================================================
# Step 6: Install or upgrade AWS Load Balancer Controller via Helm
# ============================================================
def install_controller(cluster_name, region, vpc_id):
    print("\n Installing or upgrading AWS Load Balancer Controller via Helm ...")

    cmd = (
        f"helm upgrade -i aws-load-balancer-controller eks/aws-load-balancer-controller "
        f"-n kube-system "
        f"--set clusterName={cluster_name} "
        f"--set region={region} "
        f"--set vpcId={vpc_id} "
        f"--set serviceAccount.create=false "
        f"--set serviceAccount.name=aws-load-balancer-controller"
    )

    run_cmd(cmd, capture_output=False)
    print("\n AWS Load Balancer Controller installation/upgrade completed successfully!")


# ============================================================
# Step 7: Validate deployment status (improved)
# ============================================================
def validate_deployment():
    print("\n Validating controller deployment status ...")
    run_cmd("kubectl rollout status deployment/aws-load-balancer-controller -n kube-system", capture_output=False)
    print(" Deployment is healthy.")

    print("\n Checking logs for credential binding ...")
    result = subprocess.run(
        'kubectl logs -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller | findstr "credentials"',
        shell=True,
        capture_output=True,
        text=True
    )

    if result.returncode == 0 and result.stdout.strip():
        print(result.stdout)
    else:
        print("  No credential-related messages found (likely healthy).")
    print(" Log check completed.")



# ============================================================
# MAIN EXECUTION
# ============================================================
if __name__ == "__main__":
    print("\n===============================")
    print(" AWS Load Balancer Controller Installer ")
    print("===============================")

    apply_crds()
    setup_helm_repo()
    cluster_name, region, vpc_id = get_cluster_info()

    verify_irsa_service_account()
    controller_already_installed()
    install_controller(cluster_name, region, vpc_id)
    validate_deployment()

    print("\n Installation Complete — Helm release linked with IRSA successfully!")
