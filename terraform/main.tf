module "k8s_namespace" {
  source = "./modules/k8s-namespace"

  name = var.namespace
  labels = {
    "app.kubernetes.io/part-of" = "flight-status-lab"
  }
}

locals {
  manifests             = fileset("${path.module}/../k8s", "*.yaml.tftpl")
  app_image_pull_policy = endswith(var.app_image, ":latest") ? "Always" : "IfNotPresent"
}

resource "kubernetes_manifest" "resources" {
  for_each = local.manifests

  manifest = yamldecode(templatefile("${path.module}/../k8s/${each.value}", {
    namespace         = var.namespace
    app_image         = var.app_image
    image_pull_policy = local.app_image_pull_policy
  }))

  depends_on = [module.k8s_namespace]
}

moved {
  from = kubernetes_namespace_v1.app
  to   = module.k8s_namespace.kubernetes_namespace_v1.this
}