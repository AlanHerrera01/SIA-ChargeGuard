# Entorno local de ChargeGuard

El entorno base levanta LocalStack, Mock Bank API y Mock Merchant API. Backend y frontend
permanecen en el perfil opcional `app` hasta que sus respectivos owners añadan sus
Dockerfiles.

## Requisitos

- Git.
- Docker Desktop (Windows/macOS) o Docker Engine con Compose 2.24 o posterior (Linux).
- GNU Make. En Windows, ejecuta los comandos desde Git Bash y comprueba `make --version`.
- Python 3.12 para los targets de seed, pruebas y formato que se completarán en sus WPs.

## Primera ejecución

En macOS, Linux o Git Bash:

```bash
git clone https://github.com/AlanHerrera01/SIA-ChargeGuard.git
cd SIA-ChargeGuard
cp .env.example .env
make up
docker compose ps
```

En PowerShell, la copia equivalente es:

```powershell
git clone https://github.com/AlanHerrera01/SIA-ChargeGuard.git
Set-Location SIA-ChargeGuard
Copy-Item .env.example .env
docker compose up --detach --build
docker compose ps
```

Comprueba los endpoints:

```bash
curl http://localhost:4566/_localstack/health
curl http://localhost:8001/health
curl http://localhost:8002/health
```

La respuesta del banco incluye `{"status":"ok","dataset_version":"1"}` y la del
comercio incluye `{"status":"ok"}`.

## Comandos disponibles

| Comando | Acción |
|---|---|
| `make up` | Construye y levanta LocalStack y los dos mocks. |
| `make up-all` | Levanta también backend y frontend mediante el perfil `app`. |
| `make down` | Detiene el proyecto y elimina sus volúmenes. |
| `make logs` | Sigue los logs de todos los servicios. |
| `make seed` | Ejecuta el seed local, disponible desde WP-5. |
| `make demo-reset` | Restablece la demo, disponible desde WP-5. |
| `make test` | Ejecuta las pruebas de los mocks. |
| `make fmt` | Formatea Python y Terraform. |
| `make clean` | Elimina contenedores, volúmenes e imágenes construidas localmente. |

No uses `make up-all` hasta que existan `backend/Dockerfile` y `frontend/Dockerfile`.

## Solución de problemas

### Puerto ocupado

Si aparece `address already in use`, identifica el proceso que usa 4566, 8001 o 8002 y
detén solo ese proceso. En Windows:

```powershell
Get-NetTCPConnection -LocalPort 4566,8001,8002 -ErrorAction SilentlyContinue
```

En macOS o Linux:

```bash
lsof -i :4566 -i :8001 -i :8002
```

Después ejecuta `make up` de nuevo. No cambies los puertos sin coordinarlo: forman parte
del contrato local.

### Docker Desktop sin WSL2 en Windows

Docker Desktop debe usar contenedores Linux y el motor basado en WSL2. En Settings >
General activa **Use the WSL 2 based engine**; luego verifica `wsl --status` desde
PowerShell. Si WSL no está instalado, sigue la guía oficial de Microsoft, reinicia Windows
y vuelve a abrir Docker Desktop antes de ejecutar `make up`.

### LocalStack tarda en estar healthy

El healthcheck espera hasta 110 segundos. Revisa el progreso con:

```bash
docker compose logs localstack
docker compose ps
```

Si supera ese tiempo, confirma que Docker tenga memoria disponible y que una VPN o proxy
no bloquee la descarga de la imagen. Luego ejecuta `make down` y `make up`.

### `make` no está disponible en Windows

Git Bash no incluye GNU Make por defecto. Instálalo con el gestor aprobado por tu equipo
o usa directamente los comandos `docker compose` mostrados arriba. No ejecutes targets de
seed, pruebas o formato desde PowerShell hasta tener también `python` y `terraform` en
`PATH`.
