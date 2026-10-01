variable "namespace" {
  description = "Namespace where the application and monitoring stack run."
  type        = string
  default     = "flight-status"
}

variable "app_image" {
  description = "Container image used by the flight-status Deployment."
  type        = string
  default     = "flight-status:local"
}

variable "kubeconfig_path" {
  description = "Optional path to the kubeconfig for the active Minikube cluster."
  type        = string
  default     = "~/.kube/config"
}

variable "kube_api_server" {
  description = "Optional Kubernetes API URL override for containerized Terraform runs."
  type        = string
  default     = ""
}