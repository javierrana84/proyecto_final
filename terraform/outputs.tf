output "namespace" {
  description = "Kubernetes namespace hosting the application."
  value       = module.k8s_namespace.name
}

output "ingress_host" {
  description = "Host configured on the local Ingress resource."
  value       = "flight.local"
}