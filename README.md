# Flight Status DevOps Lab

Aplicación web para consultar vuelos por número IATA (por ejemplo, `IB6842`). Flask consulta AirLabs desde el backend y nunca entrega la API key al navegador. El repositorio integra Docker multi-stage, Terraform, Minikube, Kubernetes, GitHub Actions, SAST/DAST, Prometheus y Grafana.

## Arquitectura

```text
DESPLIEGUE LOCAL (MINIKUBE)

         +-- port-forward :8081 --+
         |                        v
[Navegador] -------------+                   [Service app :80]
   |                                             |
   +-- port-forward :3000 --> [Grafana]           v
              |         [Deployment Flask]
              |                |
              |                +-- HTTPS --> [AirLabs API]
              |                |                 ^
              |                +-- usa Secret --+
              |                   AIRLABS_API_KEY
              |
              +-- datasource --> [Prometheus]
                      ^
                      +-- scrape /metrics
                      cada 15 segundos
                      desde Service app

[Terraform] -- crea namespace, Services, Deployments, Ingress y HPA

CI/CD (GITHUB ACTIONS, ENTORNO EFIMERO)

[Push a main] --> [Tests + SAST + pip-audit + build]
          |
          v
        [GHCR, imagen por commit SHA]
          |
          v
        [Terraform + Minikube temporal] --> [ZAP DAST]
          |
          +----------------------------> minikube delete
```

Terraform administra un namespace y sus recursos Kubernetes a través de un módulo reutilizable. Minikube crea el clúster local; no se provisiona una nube ni recursos con costo. El HPA mantiene de 1 a 3 réplicas para el laboratorio.

## Requisitos

- Docker
- Minikube y `kubectl`
- Terraform `1.12.2` (o una versión compatible con `terraform/versions.tf`)
- Una cuenta y API key de AirLabs. Revisa en su sitio la cuota y la cobertura disponibles para tu cuenta; los vuelos devueltos dependen del plan y de la disponibilidad del proveedor.

## 1. Preparar la API

1. Regístrate en AirLabs y crea una API key.
2. No la pegues en el código, README, commits ni conversaciones. Para Docker local, copia `.env.example` a `.env` y coloca la clave en ese archivo ignorado por Git.
3. El endpoint puede cambiarse con `FLIGHT_API_URL`; por defecto es `https://airlabs.co/api/v9/flights`.

La interfaz consulta por `flight_iata`; admite códigos IATA como `IB6842` o `AA100`. El backend limita la respuesta a campos de vuelo conocidos y establece un timeout de 8 segundos. Cuando AirLabs devuelve latitud/longitud válidas, la ficha muestra un enlace a Google Maps construido como Maps URL; no requiere una clave de Google.

## 2. Ejecutar y probar con Docker

```bash
docker build -t flight-status:local .
docker run --rm --name flight-status -p 8080:8080 --env-file .env flight-status:local
```

El build ejecuta primero las pruebas unitarias y solo produce la imagen runtime si pasan. La imagen runtime usa Python slim, instala dependencias desde wheels y ejecuta Gunicorn como usuario no-root.

- App: <http://localhost:8080>
- Health: <http://localhost:8080/health>
- Readiness: <http://localhost:8080/ready>
- Métricas Prometheus: <http://localhost:8080/metrics>

Para ejecutar solo las pruebas, puedes construir el target de test con `docker build --target test .`.

Prueba manual del endpoint local:

```bash
curl -fsS http://localhost:8080/health
curl -fsS 'http://localhost:8080/api/flights?flight_iata=AA73'
```

La disponibilidad del vuelo depende de AirLabs; usa un número activo. En la ficha del vuelo, el enlace **Abrir posición en Google Maps** aparece solo si las coordenadas son numéricas y están dentro de rango.

## 3. Desplegar en Minikube con Terraform

Inicia Minikube y habilita los complementos que requiere Ingress y el HPA:

```bash
minikube start --driver=docker
minikube addons enable ingress
minikube addons enable metrics-server
docker build -t flight-status:local .
minikube image load flight-status:local
terraform -chdir=terraform init
terraform -chdir=terraform plan -var='app_image=flight-status:local'
terraform -chdir=terraform apply -var='app_image=flight-status:local'
```

Terraform crea `flight-status` y aplica Deployment, Service, Ingress, HPA, Prometheus y Grafana. Para mantener secretos fuera del estado de Terraform, crea el Secret Kubernetes por separado. En Bash, introduce la clave en el prompt sin que aparezca en pantalla:

```bash
read -rsp 'AirLabs API key: ' AIRLABS_API_KEY && printf '\n'
printf '%s' "$AIRLABS_API_KEY" | kubectl -n flight-status create secret generic flight-api \
  --from-file=api-key=/dev/stdin --dry-run=client -o yaml | kubectl apply -f -
unset AIRLABS_API_KEY
```

Con el Secret creado, ejecuta el script para reaplicar Terraform, renovar la app y abrir los túneles locales:

```bash
./scripts/deploy-minikube.sh
```

El script mantiene abiertos los port-forwards de la aplicación (`8081`) y Grafana (`3000`); si ya hay un Grafana respondiendo en el puerto `3000`, reutiliza ese túnel. Por eso la terminal queda ocupada mientras el script espera. La app y Grafana no corren en esa terminal: están dentro de Pods administrados por Deployments de Kubernetes. Al presionar `Ctrl-C` se cierran los túneles locales, pero los Pods y Minikube siguen activos. Para volver a abrir los accesos, ejecuta el script otra vez. Abre <http://localhost:8081>; el enlace **Abrir dashboard** lleva a <http://localhost:3000>. Si el puerto `8081` está ocupado puedes cambiarlo con `APP_LOCAL_PORT=8082 ./scripts/deploy-minikube.sh`. Para usar la imagen publicada, configura `APP_IMAGE=<tu-usuario>/flight-status:latest`. El tag `latest` se descarga al reiniciar; los tags locales como `flight-status:local` usan la imagen cargada en Minikube.

El script es una comodidad para desarrollo local. En un despliegue real, Terraform puede ejecutarse desde CI/CD sin mantener una terminal abierta ni usar `kubectl port-forward`; el acceso se configura mediante Ingress, un balanceador o la red privada de la plataforma.

Si rotas la clave, vuelve a aplicar el Secret y reinicia los Pods para que reciban el nuevo valor:

```bash
kubectl rollout restart deployment/flight-status -n flight-status
```

Verifica el despliegue:

```bash
kubectl get pods,services,ingress,hpa -n flight-status
curl --resolve flight.local:80:$(minikube ip) http://flight.local/health
```

Si el host `flight.local` no es accesible desde tu equipo (por ejemplo, en algunos entornos WSL), usa las URLs locales que mantiene abiertas el script.

## 4. Prometheus y Grafana

La aplicación, Prometheus y Grafana son Deployments separados dentro del mismo clúster y namespace. Prometheus consulta `/metrics` en el Service interno de la app cada 15 segundos; Grafana consulta a Prometheus mediante su Service interno. Los Services son `ClusterIP`, así que no se publican a Internet. El script abre el port-forward de Grafana. Para Prometheus, abre un túnel aparte si lo necesitas:

```bash
kubectl port-forward -n flight-status service/prometheus 9090:9090
```

- Prometheus: <http://localhost:9090>; comprueba el target `flight-status` en `/targets`.
- Grafana: <http://localhost:3000>; carga el dashboard provisionado `Flight status service`. Este laboratorio usa acceso anónimo con rol `Viewer`, así que no hay credenciales de login guardadas en el repositorio ni en Terraform. No expongas el servicio fuera del equipo.

Genera solicitudes en la app y revisa en Grafana las solicitudes por segundo y la latencia p95. El HPA usa CPU y escala entre 1 y 3 Pods; la métrica puede tardar unos minutos en aparecer.

En una instalación real, el stack de monitoreo puede desplegarse y administrarse por separado de la aplicación. Prometheus debe tener conectividad privada hacia el endpoint de métricas de la app, o recibirlas a través de un backend compatible mediante remote write; Grafana se configura para consultar ese Prometheus o backend central. No es necesario ejecutar el script local ni exponer los Services de monitoreo públicamente.

## 5. Publicar la imagen en Docker Hub

```bash
docker login
# usa tu usuario/organización de Docker Hub

docker build -t <tu-usuario>/flight-status:latest .
docker push <tu-usuario>/flight-status:latest
```

Después de publicarla, puedes usar la imagen directamente en Minikube o en una infraestructura remota con:

```bash
terraform -chdir=terraform apply -var='app_image=<tu-usuario>/flight-status:latest'
```

## 6. Reproducir desde cero

```bash
git clone https://github.com/<usuario>/<repositorio>.git
cd <repositorio>
cp .env.example .env
# añade tu AIRLABS_API_KEY en .env o en el Secret de Kubernetes

docker login
docker build -t flight-status:local .
minikube start --driver=docker
minikube addons enable ingress
minikube addons enable metrics-server
minikube image load flight-status:local
terraform -chdir=terraform init
terraform -chdir=terraform plan -var='app_image=flight-status:local'
terraform -chdir=terraform apply -var='app_image=flight-status:local'
```

Si quieres publicar la imagen en Docker Hub y reutilizarla desde el clúster:

```bash
docker login
# usa tu usuario/organización de Docker Hub

docker build -t <tu-usuario>/flight-status:latest .
docker push <tu-usuario>/flight-status:latest
terraform -chdir=terraform apply -var='app_image=<tu-usuario>/flight-status:latest'
```

## 7. CI/CD y seguridad

`.github/workflows/pipeline.yml` corre en pull requests y pushes a `main`:

1. Ejecuta las pruebas unitarias, Bandit (SAST), pip-audit (dependencias vulnerables), build Docker y `terraform fmt/init/validate`.
2. En pushes a `main`, construye la imagen y la publica en GHCR con el SHA del commit.
3. Crea un Minikube efímero, aplica Terraform, despliega la imagen y ejecuta ZAP Baseline DAST, guardando el reporte como artifact. Configura `AIRLABS_API_KEY` en **Settings → Secrets and variables → Actions** para probar consultas reales; si no existe, el workflow usa un placeholder no funcional para validar el despliegue y DAST sin gastar cuota.

El clúster de Actions es efímero y se elimina al final del job. El despliegue local que haces con Terraform permanece hasta destruirlo.

Para ejecutar el flujo remoto, sube los cambios a `main` en el repo configurado. Los checks locales no sustituyen la evidencia de la corrida remota: guarda el enlace a la ejecución, estado de cada job y artifact ZAP.

## 8. FinOps y limpieza

Este proyecto no crea recursos de nube facturables. Para el clúster local, el HPA limita el escalado a 3 réplicas; cada Deployment tiene requests/limits, Prometheus conserva solo 24 horas y sus datos son efímeros.

Al terminar:

```bash
terraform -chdir=terraform destroy
minikube stop
```

`terraform destroy` elimina el namespace y todos sus recursos del proyecto.

## 9. Evidencias para la entrega

Inserta las capturas directamente en `docs/INFORME_ENTREGA.md`, junto a la sección que documenta cada prueba. Luego exporta ese informe como PDF; no hace falta una carpeta de evidencias separada.

Validaciones locales observadas el 2026-09-30:

- `docker build -t flight-status:local .`: correcto; el stage `test` ejecutó 6 tests y terminó `OK`.
- `python -m unittest discover -s tests -v`: 6 tests aprobados, incluida validación del input, manejo de API key, mapping de respuesta AirLabs y métricas.
- `bandit -q -r app.py`: terminó sin hallazgos reportados.
- `pip-audit -r requirements.txt`: `No known vulnerabilities found`.
- `terraform fmt -check -recursive` y `terraform validate`: correctos.
- `terraform plan` contra Minikube: `0 to add, 0 to change, 0 to destroy`.
- Minikube: app, Prometheus y Grafana `1/1`; HPA entre 1 y 3 réplicas y métrica CPU disponible.
- Prometheus: target `flight-status` en estado `up=1`; Grafana entrega el dashboard `Flight status service`.
- Búsqueda live: `AA73`, `LAX -> SYD`, `en-route`; la interfaz mostró latitud `-34.058034`, longitud `151.205006` y el link de Google Maps correspondiente.

El workflow remoto, la publicación de la imagen en GHCR y el DAST de ZAP se ejecutaron correctamente en el commit `95f0d56`. Esa corrida usó el placeholder porque `AIRLABS_API_KEY` no está configurado como secreto de GitHub; por eso no valida consultas reales a AirLabs.

Incluye en el informe las capturas propias correspondientes (no incluyas API keys):

- Build Docker y resultado de los tests.
- Recursos de Minikube listos y salida de Terraform.
- Búsqueda de vuelo y enlace de Google Maps.
- Dashboard de Grafana y target de Prometheus.
- [Corrida exitosa de GitHub Actions](https://github.com/javierrana84/proyecto_final/actions/runs/36808277985).
- [Reporte JSON de ZAP](zap-baseline-report/zap-report.json), generado por esa corrida.
