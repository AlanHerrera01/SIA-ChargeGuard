# Plan de ejecución — Infraestructura & DevOps (Ismael)

> Documento interno de trabajo. Define **qué** hay que construir, en qué orden y con qué criterio de aceptación.
> Los prompts listos para copiar/pegar a la IA ejecutora están en [prompts-executor.md](./prompts-executor.md).
> Los esquemas y contratos que el código debe respetar están en [contracts.md](./contracts.md).

---

## 1. Alcance

Según los READMEs del repo, Ismael es owner de:

| Carpeta | Qué entrega |
|---|---|
| [datasets/](../datasets/) | Datos sintéticos: 10 comercios, 6 suscripciones, 6 meses de transacciones con 3 anomalías, facturas PDF, emails EML |
| [mock-services/bank/](../mock-services/bank/) | Mock Banking API (FastAPI, puerto 8001) |
| [mock-services/merchant/](../mock-services/merchant/) | Mock Merchant Support API (FastAPI, puerto 8002) |
| [infrastructure/](../infrastructure/) | Terraform: DynamoDB, S3, IAM/OIDC, EventBridge, Lambda, API Gateway, Amplify |
| [.github/workflows/](../.github/workflows/) | CI/CD con OIDC: `ci.yml`, `deploy-infra.yml`, `deploy-app.yml` |

Y por extensión natural (nadie más lo tiene asignado y todo el equipo lo necesita): `docker-compose.yml` en la raíz, el entorno local con LocalStack, los scripts de seed, el runbook de deploy y el diagrama de arquitectura de [docs/](../docs/).

**Fuera de alcance:** `agents/` y `tools/` y `backend/` (Stephani), `frontend/` (Alan). La IA ejecutora **no toca** esas carpetas salvo lo que este plan marca explícitamente como "contrato" (por ejemplo, añadir variables a `.env.example`).

## 2. Por qué este orden

Lo primero no es Terraform. Es **desbloquear a Stephani**: sin datasets y sin mocks, ella no puede escribir ni una sola `@tool` de Strands, y el camino crítico del proyecto pasa por el agente. Por eso WP-1 a WP-5 (entorno local + datos + mocks + seed) van antes que cualquier cosa de AWS, y el objetivo es tenerlos el **sábado 5 de septiembre**.

Regla de oro del plan: **todo debe correr end-to-end en local antes de que exista un solo recurso en AWS.** Si AWS falla el 10, el proyecto sigue siendo demostrable.

## 3. Calendario

| WP | Entrega | Fecha objetivo | Bloquea a |
|---|---|---|---|
| WP-0 | Preflight: Bedrock verificado por CLI, créditos AWS, IAM users | vie 4 sep | todos |
| WP-1 | `docker-compose.yml` + LocalStack + Makefile | vie 4 sep | todos |
| WP-2 | Datasets sintéticos + generador determinista | **sáb 5 sep AM** | Stephani (crítico) |
| WP-3 | Mock Bank API | sáb 5 sep PM | Stephani |
| WP-4 | Mock Merchant API | dom 6 sep | Stephani |
| WP-5 | Seed de LocalStack (DynamoDB + S3) + `make demo-reset` | dom 6 sep | Stephani, Alan |
| WP-6 | Terraform completo (`plan` limpio) | mar 8 – jue 10 sep | deploy |
| WP-7 | CI/CD con OIDC | mié 9 – jue 10 sep | deploy |
| WP-8 | Deploy real a AWS + observabilidad + budget alarm | jue 10 – vie 11 sep | demo live |
| WP-9 | Diagrama de arquitectura, runbook, credenciales demo | sáb 12 – dom 13 sep | video/submit |

Deadline interno del equipo: **domingo 13 al mediodía**. El 14 es solo margen.

## 4. Reglas para la IA ejecutora

Estas reglas van dentro de cada prompt; se repiten aquí para revisarlas de un vistazo.

1. **Un WP = una rama = un PR.** Rama `ismael/wp-XX-slug`. Nunca commitear directo a `main`.
2. **No tocar carpetas ajenas.** Si algo de `backend/` o `agents/` parece roto, se reporta en el PR, no se arregla.
3. **Contratos primero.** [contracts.md](./contracts.md) manda. Si el código necesita divergir del contrato, se cambia primero el contrato en un PR aparte etiquetado `contract-change`.
4. **Cero secretos en el repo.** Nada de access keys, ni siquiera en ejemplos. `.env.example` solo con placeholders. Si un archivo generado contiene un ARN con account ID real, se parametriza.
5. **Todo determinista.** Mismo seed → mismos datos. Mismos delays → mismo estado. Un demo en vivo no puede depender del azar.
6. **Cada entrega corre.** No se cierra un WP sin el comando de verificación de su criterio de aceptación pegado en el PR con su salida real.
7. **Timebox de 3 horas.** Si un WP se traba más de 3h, se para, se documenta el bloqueo en el PR como draft y se avisa. AgentCore tiene timebox de 1 día completo (máximo 10 sep) — si no arranca, se despliega en Lambda y se sigue.
8. **Commits convencionales** (`feat:`, `fix:`, `chore:`, `docs:`, `ci:`) y al final del mensaje:
   `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
9. **Datos sintéticos siempre.** Ni un dato real de persona, banco o comercio. Los nombres de comercios son marcas reconocibles solo como referencia de categoría en datos claramente marcados como ficticios.
10. **Costos.** Todo `PAY_PER_REQUEST` / serverless. Nada de NAT Gateways, nada de RDS, nada de instancias EC2. Presupuesto real: 3 × $50 de créditos.

## 5. Work packages

### WP-0 — Preflight ✅ CERRADO (viernes 4 sep)

**Resuelto el 4 de septiembre.** Verificado por CLI, no por consola, en la cuenta propia de Ismael:

| Modelo | Resultado |
|---|---|
| `us.anthropic.claude-sonnet-5` | ❌ `AccessDeniedException` — "not available for this account" |
| `global.anthropic.claude-sonnet-5` | ❌ mismo error |
| `us.anthropic.claude-sonnet-4-20250514-v1:0` | ❌ `ResourceNotFoundException` — retirado, "marked by provider as Legacy" |
| **`us.anthropic.claude-sonnet-4-5-20250929-v1:0`** | ✅ responde — **el elegido** |
| `us.anthropic.claude-sonnet-4-6` | ✅ responde |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | ✅ responde |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | ✅ responde |

Dos correcciones a lo que el equipo creía:
1. **El problema nunca fue el prefijo `us.` del inference profile.** El perfil aparece `ACTIVE` en `list-inference-profiles` y aun así el `converse` falla: aparecer en la lista significa que existe en la región, no que la cuenta pueda invocarlo. El commit `f2636f6` ("use inference profile ID for Claude Sonnet 5") no arregló nada.
2. **El plan B que estaba documentado no existe.** Sonnet 4 está retirado por legacy. Nos habríamos estrellado contra eso el lunes 7.

**Decisión del equipo:** `BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0`, con `BEDROCK_MODEL_ID_FAST=us.anthropic.claude-haiku-4-5-20251001-v1:0` para los sub-agentes de bajo razonamiento (los créditos son $50 por cabeza). Ya está en `.env.example`. Si 4.5 diera problemas, cambiar a 4.6 es cambiar una variable, no código.

Comando de verificación, por si hay que repetirlo en otra cuenta:
```bash
aws bedrock-runtime converse --region us-east-1 \
  --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 \
  --messages '[{"role":"user","content":[{"text":"Respond with just OK"}]}]' \
  --query 'output.message.content[0].text' --output text
```

Pendiente en WP-0, no bloqueante:
- Los 3 integrantes piden sus $50 de créditos en la pestaña Resources de Devpost. **Deadline duro: 11 sep, 2:00 pm Ecuador.**
- Que Alan corra el mismo `converse` en la cuenta madre y confirme que Sonnet 4.5 también responde ahí, ya que el deploy final vive en su cuenta.

### WP-1 — Entorno local (viernes 4)
`docker-compose.yml` en la raíz con cinco servicios: `localstack` (4566), `mock-bank` (8001), `mock-merchant` (8002), `backend` (8000), `frontend` (5173). Los tres últimos con perfil, para poder levantar solo la parte de infra mientras backend y frontend no existen. `Makefile` con `up`, `down`, `logs`, `seed`, `demo-reset`, `test`, `fmt`. Healthchecks en todos los servicios y `depends_on: condition: service_healthy`.

Además: quitar `.terraform.lock.hcl` del `.gitignore` — ese archivo **sí** debe versionarse para que CI y las tres máquinas usen los mismos providers.

**Aceptación:** `make up` deja `docker compose ps` con todo `healthy`; `make down` limpia sin residuos.

### WP-2 — Datasets sintéticos (sábado 5, prioridad máxima)
`datasets/generate.py` determinista con `--seed 42`, que escribe `merchants.json`, `subscriptions.json`, `transactions.json`, `ground_truth.json`, `invoices/*.pdf`, `emails/*.eml` según [contracts.md §1](./contracts.md). Ventana de 6 meses **relativa a una fecha ancla fija** (`--as-of 2026-09-14`) para que el demo no envejezca.

**Aceptación:** correr el generador dos veces produce archivos idénticos (`git status` limpio); un test valida que hay exactamente 3 anomalías, que ninguna transacción trae etiqueta de anomalía, y que ningún comercio limpio tiene desviación > 0.5%.

### WP-3 — Mock Bank API (sábado 5)
FastAPI según [contracts.md §2](./contracts.md), en memoria, cargando los JSON al arrancar. Dockerfile, `requirements.txt`, tests con `pytest` + `httpx`. Sirve también `GET /health` para el healthcheck de compose.

**Aceptación:** `pytest mock-services/bank` verde; `curl localhost:8001/users/usr_demo/transactions?limit=5` devuelve 5 transacciones ordenadas desc; `POST /transactions/notify` entrega el webhook a un receptor de prueba.

### WP-4 — Mock Merchant API (domingo 6)
FastAPI según [contracts.md §3](./contracts.md). La máquina de estados se calcula desde `created_at` en cada `GET`, sin workers. Soporta `X-Demo-Scenario` y `X-Demo-Speed`.

**Aceptación:** test que recorre el camino completo submitted → counter_offer → reject → escalated → resolved_full con `X-Demo-Speed: instant`, y otro que verifica 409 en transiciones inválidas.

### WP-5 — Seed local (domingo 6)
`scripts/seed_local.py`: crea en LocalStack las 3 tablas DynamoDB y el bucket S3 con los índices exactos de [contracts.md §4](./contracts.md), carga transacciones a DynamoDB y sube invoices/emails/terms a S3. Idempotente. `make demo-reset` = borrar + recrear + recargar + resetear los dos mocks, en menos de 30 segundos.

**Aceptación:** tras `make seed`, un `scan` a `chargeguard-transactions` devuelve el mismo número de items que `transactions.json`, y `aws s3 ls` (con `--endpoint-url`) lista los PDFs.

### WP-6 — Terraform (8–10 sep)
Módulos separados: `dynamodb`, `s3`, `iam`, `lambda_api`, `eventbridge`, `amplify`, `agentcore`. Un solo environment (`dev`). Backend remoto S3 + lock DynamoDB creado por un `bootstrap/` aparte que se aplica una sola vez. Todo con `tags` comunes (`Project=ChargeGuard`, `ManagedBy=Terraform`). Rol OIDC de GitHub con trust condicionado a `repo:AlanHerrera01/SIA-ChargeGuard:*`. Rol de ejecución del agente con `bedrock:InvokeModel` limitado al inference profile en uso.

**Aceptación:** `terraform validate` y `terraform plan` limpios sobre la cuenta real, sin recursos que cuesten estando idle más allá de S3/DynamoDB on-demand.

### WP-7 — CI/CD (9–10 sep)
- `ci.yml` en cada PR: `ruff` + `pytest` de mocks y backend, `terraform fmt -check` + `validate`, `npm ci && npm run build` del frontend. Paths filtrados para que cada job corra solo si su carpeta cambió.
- `deploy-infra.yml` en merge a `main` con cambios en `infrastructure/`: `plan` y `apply` con aprobación de environment.
- `deploy-app.yml` en merge a `main` con cambios en `backend/`, `agents/` o `frontend/`.
- Autenticación por OIDC (`aws-actions/configure-aws-credentials@v4` con `role-to-assume`). **Cero secretos de AWS en GitHub.**
- Proteger `main`: PR obligatorio, 1 review, checks de `ci.yml` en verde.

**Aceptación:** un PR de prueba corre CI en verde; un merge a `main` ejecuta un deploy real observable en CloudWatch.

### WP-8 — Deploy y observabilidad (10–11 sep)
Backend en Lambda tras API Gateway, frontend en Amplify Hosting, agente en AgentCore Runtime (con la regla del timebox: si el 10 al final del día no arranca, el agente se empaqueta en la misma Lambda del backend y se documenta como decisión consciente). Log groups con retención de 7 días, dashboard de CloudWatch con invocaciones, errores y latencia del agente, y **AWS Budget de $40 con alerta al 50% y 80%**.

**Aceptación:** la URL pública del frontend abre, dispara un caso end-to-end contra los mocks desplegados y muestra la decision card. Esa URL es el "live demo link" de Devpost.

### WP-9 — Documentación y cierre (12–13 sep)
Diagrama de arquitectura (`docs/architecture.excalidraw` + `architecture.png`), runbook de deploy y teardown, `docs/demo-script.md` con el guion exacto del video, credenciales de demo publicadas en el README, y completar las secciones TBD del README que dependen de infra (Local Setup, AWS Deployment, AWS Services Used).

**Aceptación:** una persona ajena al equipo clona el repo, corre `cp .env.example .env && make up && make seed` y ve el sistema funcionando sin preguntar nada.

## 6. Riesgos y planes B

| Riesgo | Disparador | Plan B |
|---|---|---|
| ~~Sonnet 5 no se activa~~ | ~~7 sep~~ | **Materializado y resuelto el 4 sep**: Sonnet 5 no es invocable y Sonnet 4 está retirado. Vamos con `us.anthropic.claude-sonnet-4-5-20250929-v1:0`. Ver WP-0. |
| AgentCore no arranca | fin del 10 sep | Agente dentro de la Lambda del backend; se documenta en el README |
| Amplify da problemas | 11 sep | S3 + CloudFront con el build estático de Vite |
| LocalStack inestable | cualquier momento | Tablas reales en DynamoDB de la cuenta dev con prefijo `dev-`; el código no cambia, solo `AWS_ENDPOINT_URL` |
| Créditos AWS agotados | alerta de budget | Todo es on-demand: `terraform destroy` y volver a levantar para el video |
| Alguien se cae del equipo | — | Backup owners: Stephani respalda a Alan, Alan a Ismael, Ismael a Stephani |

## 7. Cómo se reporta el avance

Cada PR de la IA ejecutora debe cerrar con este bloque:

```
## WP-XX — <nombre>
**Estado:** completo | bloqueado
**Archivos:** <lista>
**Verificación:** <comando + salida real pegada>
**Contratos tocados:** ninguno | <cuáles y por qué>
**Siguiente:** WP-YY
**Bloqueos:** ninguno | <qué y qué se necesita de quién>
```

Si dice "bloqueado", el PR queda en draft y el bloqueo se lleva al standup de las 9:00 am.
