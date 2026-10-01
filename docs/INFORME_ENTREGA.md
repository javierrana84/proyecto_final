# PF_APELLIDO - Pipeline DevOps para Flight Status

> Antes de exportar a PDF, reemplazar `APELLIDO`, completar fecha y enlace del repositorio, y agregar las evidencias reales indicadas abajo.

## 1. Introducción

El proyecto implementa una aplicación web para consultar información de vuelos por número IATA. Flask actúa como backend entre el navegador y AirLabs, de modo que la API key no queda expuesta al frontend. Cuando el proveedor entrega coordenadas válidas, la ficha añade un enlace directo a Google Maps sin requerir API key de Google. La solución demuestra contenedores, infraestructura como código, CI/CD, seguridad y observabilidad.

## 2. Arquitectura

- Aplicación Flask con página de búsqueda, health check, readiness y métricas Prometheus.
- Imagen Docker multi-stage: creación de wheels, pruebas automatizadas y runtime slim no-root.
- Minikube como clúster Kubernetes local, sin recursos cloud facturables.
- Terraform con variables y módulo reutilizable para crear namespace y aplicar recursos Kubernetes.
- Kubernetes: Deployment, Service, Ingress, HPA, Secret, Prometheus y Grafana.
- GitHub Actions: tests, Bandit, pip-audit, build Docker, validación Terraform y publicación GHCR; despliegue de prueba en Minikube efímero y DAST con ZAP Baseline.

## 3. Construcción de la aplicación e imagen

El frontend permite ingresar un código IATA, por ejemplo `IB6842`. Flask valida el formato, consulta el endpoint HTTPS configurable de AirLabs con timeout y devuelve solo los campos permitidos. Las pruebas unitarias usan respuestas simuladas, así no consumen cuota externa. Para coordenadas presentes, el navegador crea una URL de Google Maps con `URLSearchParams` y abre una pestaña con `rel="noopener noreferrer"`; valores fuera de rango no generan el enlace.

El Dockerfile separa la creación de dependencias, la ejecución de tests y la imagen final. El contenedor corre con usuario sin privilegios y expone `/health` para liveness y `/ready` para readiness.

**Comandos de validación ejecutados:**

```text
docker build -t flight-status:local .
docker run -d -p 8080:8080 flight-status:local
curl http://localhost:8080/health
curl 'http://localhost:8080/api/flights?flight_iata=AA73'
```

El 2026-09-30 la interfaz consultó `AA73`, mostrando `LAX -> SYD`, `en-route`, posición `-34.058034, 151.205006` y un enlace Google Maps formado con dichas coordenadas. Se probó la página desplegada en Minikube por port-forward; no se incluye la API key en la respuesta ni en este informe.

**Evidencia:** añadir captura del build y los tests; captura de la ficha del vuelo con el link. La ejecución local puede repetirse siguiendo `README.md`.

## 4. Terraform y Kubernetes

Terraform usa el provider oficial Kubernetes sobre el contexto Minikube. El módulo `terraform/modules/k8s-namespace` define el namespace de forma reutilizable; los manifiestos templados parametrizan namespace e imagen. El Secret de AirLabs se crea con `kubectl` para que su valor no quede guardado en el state de Terraform.

El Deployment solicita CPU/memoria, limita su consumo, usa probes y filesystem de solo lectura. El Service es interno; Ingress define el host local `flight.local`; HPA escala de 1 a 3 Pods según CPU.

**Validación local observada:** Terraform `fmt` y `validate` terminaron correctamente. `plan` quedó en `0 to add, 0 to change, 0 to destroy`, lo que confirma que Terraform coincide con los recursos aplicados. App, Prometheus y Grafana quedaron `1/1`; Prometheus devolvió `up=1` para el target `flight-status`; Grafana expuso el dashboard `Flight status service`; el HPA calculó CPU respecto a su target de 70% y conserva el rango de 1 a 3 Pods.

**Evidencia:** añadir una captura de `terraform plan` y `kubectl get pods,services,ingress,hpa -n flight-status`. Usa `kubectl port-forward` para el health check si el Ingress no es enrutable desde el host.

## 5. CI/CD y DevSecOps

En pull requests y pushes a `main`, el pipeline instala dependencias, ejecuta unittest, Bandit y pip-audit, construye la imagen y valida formato/sintaxis Terraform. En `main`, vuelve a construir y publica la imagen en GitHub Container Registry con el SHA del commit. Un runner efímero levanta Minikube, aplica Terraform, despliega la imagen y ejecuta ZAP Baseline contra la aplicación. Si `AIRLABS_API_KEY` no está configurado como GitHub Actions secret, usa un placeholder para que el despliegue/DAST funcionen sin cuota; las consultas reales requieren el secreto.

**Estado de verificación:** la corrida [95f0d56](https://github.com/javierrana84/proyecto_final/actions/runs/36808277985) finalizó correctamente: tests/SAST, publicación de la imagen en GHCR, despliegue efímero y DAST. El [reporte JSON de ZAP](../zap-baseline-report/zap-report.json) quedó guardado en el repositorio. El workflow usó un placeholder porque `AIRLABS_API_KEY` no está configurado como secreto de GitHub; por lo tanto, el DAST no probó consultas reales a AirLabs.

**Evidencia:** insertar una captura de la corrida en GitHub Actions y conservar el enlace al JSON de ZAP.

## 6. Monitoreo

Prometheus scrapea `/metrics` cada 15 segundos. Grafana usa Prometheus como datasource y provisiona un dashboard con salud del servicio, llamadas HTTP, latencia p95 y consumo de recursos internos del proceso de la app (`app_uptime_seconds`, `app_process_cpu_seconds_total`, `app_process_memory_bytes`). Tanto Prometheus como Grafana se exponen vía `port-forward`; en este laboratorio Grafana funciona con acceso anónimo en rol `Viewer`, sin credenciales almacenadas en el repositorio ni en Terraform.

**Evidencia:** insertar captura del dashboard con tráfico generado y del target `flight-status` en Prometheus.

## 8. Pasos rápidos de entrega

```bash
git clone https://github.com/<usuario>/<repositorio>.git
cd <repositorio>
cp .env.example .env
# añade la AIRLABS_API_KEY en .env o en el Secret de Kubernetes

docker build -t flight-status:local .
minikube start --driver=docker
minikube addons enable ingress metrics-server
minikube image load flight-status:local
terraform -chdir=terraform init
terraform -chdir=terraform plan -var='app_image=flight-status:local'
terraform -chdir=terraform apply -var='app_image=flight-status:local'
```

Para publicar la imagen en Docker Hub y reutilizarla desde el cluster:

```bash
docker login
# opcional: usa tu usuario de Docker Hub

docker build -t <usuario>/flight-status:latest .
docker push <usuario>/flight-status:latest
terraform -chdir=terraform apply -var='app_image=<usuario>/flight-status:latest'
```

## 7. FinOps y seguridad

No se aprovisionan instancias ni servicios cloud pagados. Minikube corre local; el HPA tiene máximo de 3 réplicas; los Pods declaran requests/limits; Prometheus conserva 24 horas y almacenamiento efímero. Para liberar recursos, se ejecutan `terraform destroy` y `minikube stop`.

La clave API se guarda en `.env` local ignorado o en un Secret de Kubernetes/GitHub Actions. Terraform state, archivos `.env` y credenciales no deben subirse al repositorio.

## 8. Reproducción y limitaciones

Los pasos completos para instalar dependencias, desplegar en Minikube, validar métricas y limpiar el entorno están en `README.md`. La cobertura y cuota de vuelos dependen del plan vigente de AirLabs; la búsqueda no puede garantizar que un vuelo histórico o inactivo aparezca. El clúster local no simula una VPC ni infraestructura cloud y el deploy de GitHub Actions es temporal.

## 9. Registro de evidencias

| Evidencia | Ruta o enlace | Commit/fecha |
| --- | --- | --- |
| Docker build y tests | Verificación local: build correcto, 6 tests OK | 2026-09-30 |
| Terraform y Kubernetes | Plan sin cambios; despliegues `1/1`; HPA activo | 2026-09-30 |
| Consulta real de vuelo | AA73, LAX -> SYD, en-route; link Maps visible | 2026-09-30 |
| Prometheus/Grafana | Target `up=1`; dashboard disponible por API | 2026-09-30 |
| GitHub Actions y reporte ZAP | [Corrida 95f0d56](https://github.com/javierrana84/proyecto_final/actions/runs/36808277985); [reporte JSON](../zap-baseline-report/zap-report.json) | 2026-10-01 |
| Capturas para el PDF | Pendiente de insertar directamente en este informe | Pendiente |

## 10. Conclusión

La solución integra la aplicación, una imagen probada, el aprovisionamiento reproducible de recursos Kubernetes locales, una consulta real a AirLabs y telemetría Prometheus/Grafana. Las pruebas locales, la publicación en GHCR y el DAST remoto están verificados; el workflow usó una clave placeholder y no realizó consultas reales a AirLabs. Inserta las capturas finales antes de exportar este documento como `PF_APELLIDO.pdf` y subirlo a Drive.