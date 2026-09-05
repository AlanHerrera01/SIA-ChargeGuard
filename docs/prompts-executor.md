# Prompts para la IA ejecutora — track Infra/DevOps

Cómo usar este archivo:

1. Pega **el Prompt Maestro (§0) una sola vez** al abrir la sesión con la IA ejecutora. Establece contexto, alcance y reglas.
2. Después pega **un prompt de WP por vez**, en orden. No le des dos WPs juntos: cada uno termina en un PR verificable.
3. Cuando responda, exige el bloque de reporte del final. Si no verificó con un comando real, no está hecho.
4. Si un WP se traba más de 3 horas, para y escala al standup.

Los prompts asumen que la IA ejecutora trabaja **dentro del repo clonado** y puede leer [contracts.md](./contracts.md) y [execution-plan-infra.md](./execution-plan-infra.md).

---

## §0 — Prompt maestro (pegar primero, una sola vez)

```
Vas a trabajar en ChargeGuard, un proyecto para el AWS Agents for Humans Hackathon 2026
(track Everyday Agents, deadline 14 de septiembre 2026). Repo:
https://github.com/AlanHerrera01/SIA-ChargeGuard

QUÉ ES EL PRODUCTO
Un agente autónomo que monitorea cobros recurrentes de suscripciones, detecta anomalías
(subidas de precio silenciosas, cobros duplicados, cobros después de cancelar), reúne
evidencia, presenta el reclamo al comercio y negocia el reembolso. Solo interrumpe al
humano cuando hay una decisión real que tomar: contraoferta del comercio, confianza baja
en la anomalía, o monto sobre un umbral.

STACK
- Agente: Strands Agents SDK (Python), patrón Agents-as-Tools, sobre Amazon Bedrock
  (Claude Sonnet 4.5, inference profile us.anthropic.claude-sonnet-4-5-20250929-v1:0 —
  verificado por CLI el 4 sep; Sonnet 5 NO es invocable desde nuestras cuentas y Sonnet 4
  está retirado, así que no lo "corrijas" de vuelta)
- Runtime: Amazon Bedrock AgentCore Runtime
- Backend: FastAPI en AWS Lambda + API Gateway
- Frontend: React + TypeScript + Vite + Tailwind + shadcn/ui en AWS Amplify Hosting
- Storage: DynamoDB + S3. Eventos: EventBridge. Observabilidad: CloudWatch
- IaC: Terraform. CI/CD: GitHub Actions con OIDC (sin credenciales largas en secrets)
- Mocks locales: Mock Bank API y Mock Merchant Support API, ambas FastAPI en Docker Compose
- Todos los datos son sintéticos. No hay integración con bancos ni comercios reales.

TU ALCANCE — eres el track de Infraestructura y DevOps
Eres owner exclusivo de: datasets/, mock-services/bank/, mock-services/merchant/,
infrastructure/, .github/workflows/, docker-compose.yml, scripts/ y los docs de deploy.
NO tocas agents/, tools/, backend/ ni frontend/: tienen otros owners. Si ves un problema
ahí, lo reportas en el PR, no lo arreglas.

DOCUMENTOS QUE MANDAN
- docs/contracts.md: esquemas de datos y contratos de API. Es la fuente de verdad. Si tu
  código necesita divergir, primero cambias el contrato en un PR aparte etiquetado
  contract-change; nunca en silencio.
- docs/execution-plan-infra.md: los work packages, su orden y sus criterios de aceptación.
Léelos antes de escribir código.

REGLAS INNEGOCIABLES
1. Un work package = una rama (ismael/wp-XX-slug) = un PR. Nunca commits directos a main.
2. Cero secretos en el repo: ni access keys, ni account IDs hardcodeados, ni tokens.
   .env.example solo con placeholders.
3. Todo determinista: mismo seed, mismos datos; mismos delays, mismo estado. Un demo en
   vivo no puede depender del azar.
4. Nada se cierra sin verificación: pega en el PR el comando que corriste y su salida real.
   Si no lo corriste, dilo; no inventes salidas.
5. Costos: todo serverless y on-demand. Prohibido NAT Gateway, RDS, EC2, cualquier cosa que
   cobre estando idle. El presupuesto total del equipo son $150 en créditos.
6. Commits convencionales (feat:, fix:, chore:, docs:, ci:) terminando con:
   Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
7. Prioridad absoluta: desbloquear al track de agentes. Los datasets y los mocks van antes
   que cualquier cosa de AWS.
8. Si algo te traba más de 3 horas, para, deja el PR en draft y explica exactamente qué
   necesitas y de quién.

CÓMO REPORTAS
Cada entrega termina con este bloque, sin adornos:

## WP-XX — <nombre>
**Estado:** completo | bloqueado
**Archivos:** <lista>
**Verificación:** <comando + salida real>
**Contratos tocados:** ninguno | <cuáles y por qué>
**Siguiente:** WP-YY
**Bloqueos:** ninguno | <qué y de quién dependes>

Confirma que leíste esto y que revisaste docs/contracts.md y
docs/execution-plan-infra.md, resumiendo en 5 líneas qué vas a construir y en qué orden.
No escribas código todavía.
```

---

## §1 — WP-1: Entorno local con Docker Compose

```
WP-1: entorno de desarrollo local.

Crea en la raíz del repo:

1. docker-compose.yml con cinco servicios:
   - localstack (imagen localstack/localstack, puerto 4566, SERVICES=dynamodb,s3,
     persistencia desactivada, healthcheck contra /_localstack/health)
   - mock-bank (build desde mock-services/bank, puerto 8001, healthcheck GET /health)
   - mock-merchant (build desde mock-services/merchant, puerto 8002, healthcheck GET /health)
   - backend (build desde backend/, puerto 8000, profile "app")
   - frontend (build desde frontend/, puerto 5173, profile "app")
   backend y frontend van bajo el profile "app" porque todavía no existen: `docker compose up`
   sin profile debe levantar solo localstack y los dos mocks, sin errores.
   Usa depends_on con condition: service_healthy. Variables desde .env (env_file).

2. Makefile con: up, up-all, down, logs, seed, demo-reset, test, fmt, clean.
   Que funcione en Git Bash sobre Windows (nada de sintaxis exclusiva de GNU/Linux más allá
   de make; si algo no es portable, usa un script en scripts/ y llámalo desde el Makefile).

3. Actualiza .env.example con las variables nuevas de docs/contracts.md §4.3
   (BACKEND_WEBHOOK_URL, DATASET_DIR, DEMO_USER_ID, AWS_ENDPOINT_URL).

4. Quita .terraform.lock.hcl del .gitignore: ese archivo SÍ debe versionarse para que CI y
   las tres máquinas del equipo usen exactamente los mismos providers. Deja un comentario
   corto explicando por qué.

5. docs/local-setup.md: cómo levantar todo desde cero en Windows, macOS y Linux, con los
   errores comunes (puertos ocupados, Docker Desktop sin WSL2, LocalStack tardando en
   arrancar).

Criterio de aceptación: `make up` deja todos los servicios healthy en `docker compose ps`,
y `make down` limpia sin dejar contenedores ni volúmenes. Pega esa salida en el PR.

Nota: los Dockerfiles de mock-bank y mock-merchant todavía no existen. Créalos como parte
de este WP con un stub mínimo de FastAPI que responda GET /health, para que compose levante
verde hoy. La lógica real llega en WP-3 y WP-4.
```

---

## §2 — WP-2: Datasets sintéticos (máxima prioridad)

```
WP-2: generador de datos sintéticos. Este WP desbloquea al track de agentes, así que va
antes que todo lo demás de AWS.

Implementa datasets/generate.py siguiendo docs/contracts.md §1 al pie de la letra. Sin
desviaciones de nombres de campo: el agente y el frontend ya están codificando contra ese
esquema.

Requisitos:
- CLI: `python datasets/generate.py --seed 42 --as-of 2026-09-14 --out datasets/`
  La fecha ancla es fija para que el demo no envejezca: los 6 meses de historia se calculan
  hacia atrás desde --as-of, no desde hoy.
- Determinismo estricto: correrlo dos veces seguidas debe dejar `git status` limpio.
  Usa random.Random(seed), nada de uuid4 ni datetime.now() en los datos.
- Salidas: merchants.json (10), subscriptions.json (6, todas de usr_demo),
  transactions.json (6 meses), ground_truth.json, invoices/*.pdf, emails/*.eml
- Las tres anomalías son exactamente las de la tabla de contracts.md §1.4: anm_001
  price_hike en sub_001 sin email de aviso, anm_002 duplicate_charge en sub_003,
  anm_003 charge_after_cancellation en sub_005 con email de cancelación presente.
- Ninguna transacción lleva etiqueta de anomalía. La verdad vive solo en ground_truth.json.
- Las suscripciones limpias deben ser realmente limpias: nada que se parezca a una anomalía
  y provoque falsos positivos.
- Facturas PDF con fpdf2 (no reportlab, menos dependencias). La factura de la subida de
  precio muestra el precio nuevo, que es la evidencia que el agente va a citar.
- Emails .eml válidos RFC-822 generados con email.message.EmailMessage: recibos, una
  confirmación de cancelación de sub_005, avisos de cambio de precio de DOS suscripciones
  distintas de sub_001, y algo de ruido de marketing. Deliberadamente NO existe aviso de
  cambio de precio para sub_001.

Añade datasets/test_datasets.py con pytest que valide:
- exactamente 3 anomalías en ground_truth.json y que cada transaction_id referenciado existe
- ninguna transacción contiene claves de anomalía
- toda suscripción limpia tiene desviación máxima <= 0.5% respecto a su base_amount_usd
- todo invoice_key y terms_key apunta a un archivo que existe
- regenerar con el mismo seed produce los mismos hashes

Actualiza datasets/README.md con cómo regenerar y qué representa cada anomalía.

Criterio de aceptación: pytest verde, y `python datasets/generate.py --seed 42` dos veces
seguidas deja el árbol de git sin cambios. Pega ambas salidas.
```

---

## §3 — WP-3: Mock Bank API

```
WP-3: Mock Banking API en mock-services/bank/.

Implementa exactamente los endpoints de docs/contracts.md §2. FastAPI + Pydantic v2,
estado en memoria, datasets cargados al arrancar desde DATASET_DIR.

Detalles que importan:
- GET /users/{user_id}/transactions ordena por posted_at DESCENDENTE y pagina con cursor
  opaco (base64 del último sk). limit por defecto 100, máximo 500.
- POST /transactions/notify hace el POST del envelope transaction.posted al webhook_url
  (o a BACKEND_WEBHOOK_URL si no viene). Timeout 5s. Si el backend está caído, responde
  HTTP 200 con delivered:false — el demo no puede caerse porque el backend no esté arriba.
- POST /demo/reset recarga los JSON del disco y limpia estado en runtime.
- Errores con el formato {"error":{"code":"...","message":"..."}} de contracts.md.
- La API NUNCA expone ground_truth.json. Ni siquiera lo carga.

Entrega también: Dockerfile (python:3.12-slim, usuario no-root), requirements.txt con
versiones pinneadas, y tests con pytest + httpx.ASGITransport cubriendo: listado paginado y
ordenado, filtro por merchant_id y por rango de fechas, 404 en transacción inexistente,
entrega de webhook exitosa y fallida, y demo/reset.

Actualiza mock-services/bank/README.md con los endpoints reales y ejemplos de curl.

Criterio de aceptación: `pytest mock-services/bank` verde y `curl -s
localhost:8001/users/usr_demo/transactions?limit=5 | jq` devuelve 5 transacciones ordenadas
desc. Pega ambas salidas.
```

---

## §4 — WP-4: Mock Merchant Support API

```
WP-4: Mock Merchant Support API en mock-services/merchant/.

Implementa docs/contracts.md §3. FastAPI + Pydantic v2, estado en memoria.

El punto crítico es la máquina de estados: se calcula desde created_at en CADA GET, con
aritmética de tiempo pura. Nada de background tasks ni asyncio.sleep: el demo tiene que ser
reproducible y los tests tienen que correr en milisegundos.

- submitted -> (+1s) under_review -> (+3s) counter_offer
- accept desde counter_offer -> resolved_accepted
- reject desde counter_offer -> escalated -> (+3s) resolved_full o denied, según
  dispute_policy.escalation_outcome del comercio
- Si el comercio tiene auto_counter_offer:false, under_review va directo a resolved_full
- Monto de la contraoferta: round(requested_amount_usd * counter_offer_ratio, 2), tope
  max_refund_usd
- history[] acumula cada transición con timestamp y nota legible: es lo que el frontend
  pinta como timeline del caso, así que las notas tienen que estar escritas para un humano
- accept o reject desde un estado inválido: 409 invalid_state_transition
- Headers de demo: X-Demo-Scenario (full_refund | counter_offer | denied | slow) y
  X-Demo-Speed: instant (todos los delays a cero). El de escenario es obligatorio: es lo que
  nos deja grabar el video sin sorpresas.

Los delays vienen del dispute_policy del comercio en merchants.json, así que el servicio
carga ese dataset al arrancar y devuelve 404 merchant_not_found si el merchant_id no existe.

Entrega Dockerfile, requirements.txt pinneado y tests con pytest cubriendo: camino feliz
completo con X-Demo-Speed:instant, camino de rechazo hasta resolved_full, camino denied,
409 en transiciones inválidas, 400 en requested_amount_usd <= 0, y cada valor de
X-Demo-Scenario.

Actualiza mock-services/merchant/README.md con el diagrama de estados en ASCII y curls de
ejemplo para cada camino.

Criterio de aceptación: pytest verde, más una secuencia de curl que muestre el camino
submitted -> counter_offer -> reject -> escalated -> resolved_full. Pega la salida.
```

---

## §5 — WP-5: Seed de LocalStack

```
WP-5: aprovisionamiento y carga de datos en LocalStack.

Crea scripts/seed_local.py que, contra AWS_ENDPOINT_URL (por defecto http://localhost:4566):

1. Crea las tres tablas DynamoDB con las claves e índices EXACTOS de docs/contracts.md §4.1:
   chargeguard-transactions (PK user_id, SK sk, GSI merchant-index),
   chargeguard-cases (PK case_id, GSI user-index y status-index),
   chargeguard-decisions (PK decision_id, GSI case-index y pending-index).
   Todas PAY_PER_REQUEST.
2. Crea el bucket S3 chargeguard-evidence (nombre desde S3_BUCKET_EVIDENCE).
3. Carga transactions.json en chargeguard-transactions con batch_writer, construyendo
   sk = "{posted_at}#{transaction_id}".
4. Sube invoices/ a invoices/, emails/ a emails/ y los términos generados a terms/.
5. Es idempotente: correrlo dos veces no falla ni duplica. Si una tabla existe, la reusa.
6. Imprime un resumen al final: tablas creadas, items cargados, objetos subidos.

Crea también scripts/demo_reset.py: borra y recrea tablas, recarga datos y llama a
POST /demo/reset de los dos mocks. Debe terminar en menos de 30 segundos — es lo que vamos
a correr en vivo entre tomas del video.

Conéctalos al Makefile: `make seed` y `make demo-reset`.

Importante: el mismo script tiene que servir contra AWS real cambiando AWS_ENDPOINT_URL a
vacío. No hardcodees el endpoint de LocalStack en el cliente boto3; léelo de entorno y
pásalo solo si está definido.

Añade scripts/test_seed.py que verifique, tras el seed, que el count de la tabla coincide
con el número de transacciones del JSON y que los objetos de S3 están listados.

Criterio de aceptación: `make up && make seed` y luego un scan que devuelva el mismo número
de items que transactions.json, más `aws --endpoint-url=http://localhost:4566 s3 ls
s3://chargeguard-evidence/invoices/` listando los PDFs. Pega ambas salidas.
```

---

## §6 — WP-6: Terraform

```
WP-6: infraestructura como código en infrastructure/.

Estructura:
  infrastructure/bootstrap/     -> bucket de state + tabla de lock (se aplica UNA vez, con
                                   backend local, y se commitea el output)
  infrastructure/main.tf, variables.tf, outputs.tf, versions.tf, backend.tf
  infrastructure/modules/dynamodb, s3, iam, lambda_api, eventbridge, amplify, agentcore

Requisitos:
- Providers pinneados con ~> y .terraform.lock.hcl commiteado.
- Un solo environment (dev). Nada de workspaces ni de una jerarquía que no vamos a usar en
  11 días.
- default_tags en el provider: Project=ChargeGuard, ManagedBy=Terraform, Environment=dev.
- dynamodb: las 3 tablas de docs/contracts.md §4.1, PAY_PER_REQUEST, deletion_protection
  false (el stack tiene que poder destruirse).
- s3: bucket chargeguard-evidence-${account_id}, Block Public Access completo, SSE-S3,
  versioning off, lifecycle de expiración a 30 días.
- iam:
  * rol OIDC para GitHub Actions, con proveedor OIDC de token.actions.githubusercontent.com
    y condición sub = repo:AlanHerrera01/SIA-ChargeGuard:* (y aud = sts.amazonaws.com).
    Permisos acotados: no AdministratorAccess.
  * rol de ejecución de Lambda: logs, DynamoDB sobre las 3 tablas, S3 sobre el bucket,
    bedrock:InvokeModel y InvokeModelWithResponseStream limitado al ARN del inference
    profile en uso.
  * rol de AgentCore Runtime, mismo criterio de mínimo privilegio.
- lambda_api: función del backend (imagen o zip, tú eliges; documenta por qué) + API Gateway
  HTTP API con CORS abierto solo al dominio de Amplify.
- eventbridge: un bus y una regla para transaction.posted que dispare al backend.
- amplify: app conectada al repo, rama main, build de Vite.
- agentcore: recursos del AgentCore Runtime. Si el provider de AWS todavía no los soporta,
  NO bloquees este WP: deja el módulo con un README explicando el estado y sigue; el
  fallback es desplegar el agente dentro de la Lambda del backend.

Variables sin defaults sensibles para todo lo que dependa de la cuenta (account_id, region,
repo). Nada de account IDs literales en el código.

Añade infrastructure/README.md con el orden exacto: bootstrap primero, luego init con
backend remoto, plan, apply. Y un runbook de teardown.

Criterio de aceptación: `terraform fmt -check`, `terraform validate` y `terraform plan`
limpios contra la cuenta real. Pega el resumen del plan (cuántos recursos a crear). NO
apliques todavía: el apply es WP-8 y va con revisión del equipo.
```

---

## §7 — WP-7: CI/CD con OIDC

```
WP-7: pipelines en .github/workflows/.

1. ci.yml — en cada pull_request:
   - job lint-test-python: ruff check + pytest sobre mock-services/ y datasets/
   - job terraform: fmt -check + init -backend=false + validate
   - job frontend: npm ci + npm run build (solo si frontend/ existe; si no, skip limpio)
   Usa paths-filter para que cada job corra solo cuando su carpeta cambió, y caché de pip y
   de npm. El pipeline completo debe tardar menos de 5 minutos.

2. deploy-infra.yml — en push a main con cambios en infrastructure/:
   OIDC con aws-actions/configure-aws-credentials@v4 y role-to-assume; terraform plan,
   luego apply gateado por un environment de GitHub con required reviewer.

3. deploy-app.yml — en push a main con cambios en backend/, agents/ o frontend/:
   build y deploy de la Lambda y trigger del build de Amplify.

Reglas:
- permissions mínimas por workflow: id-token: write y contents: read. Nada más.
- CERO secretos de AWS. Solo el ARN del rol como variable de repositorio (vars, no secrets).
- Concurrency group por workflow para que dos merges seguidos no pisen el mismo apply.

Documenta en .github/workflows/README.md: qué corre cuándo, cómo se configura el rol OIDC,
y cómo proteger main (PR obligatorio, 1 review, checks de ci.yml requeridos). Incluye los
comandos de gh CLI para aplicar la protección de rama.

Criterio de aceptación: abre un PR de prueba y pega el enlace al run de CI en verde.
```

---

## §8 — WP-8: Deploy real y observabilidad

```
WP-8: llevar todo a AWS.

1. terraform apply completo. Pega los outputs (sin exponer account IDs completos).
2. Despliega el backend a Lambda y el frontend a Amplify. Los mocks también van a AWS:
   como funciones Lambda detrás del mismo API Gateway, con paths /mock/bank/* y
   /mock/merchant/*. Documenta las URLs resultantes.
3. Corre scripts/seed_local.py contra AWS real (AWS_ENDPOINT_URL vacío) para poblar las
   tablas y el bucket de verdad.
4. Observabilidad:
   - log groups con retención de 7 días (no infinita: cuesta)
   - dashboard de CloudWatch "ChargeGuard" con invocaciones, errores, duración p95 de la
     Lambda, y métricas de Bedrock si están disponibles
   - AWS Budget de $40 con alertas por email al 50% y 80%
5. Verifica el flujo end-to-end en AWS: POST /transactions/notify del mock bank desplegado
   -> webhook al backend -> caso creado en DynamoDB -> visible en la URL pública del
   frontend.
6. Escribe docs/deployment.md: prerrequisitos, orden de deploy, cómo hacer rollback, cómo
   destruir todo, y qué revisar si el demo falla en vivo.

REGLA DE TIMEBOX: AgentCore Runtime tiene hasta el final del 10 de septiembre. Si a esa hora
no está corriendo, empaqueta el agente dentro de la Lambda del backend, documenta la
decisión en el README como un trade-off consciente, y sigue. No sacrificamos el proyecto por
AgentCore.

Criterio de aceptación: la URL pública del frontend abre desde una ventana de incógnito y
completa un caso end-to-end. Esa URL es el live demo link de Devpost. Pega la URL y el
resultado de la prueba.
```

---

## §9 — WP-9: Documentación, diagrama y cierre

```
WP-9: cerrar la parte de infra para el submit.

1. docs/architecture.excalidraw + docs/architecture.png. El diagrama debe mostrar, en una
   sola vista legible a 1080p:
   - el usuario y el frontend en Amplify
   - API Gateway -> Lambda backend
   - el DisputeOrchestrator y sus 4 sub-agentes (ChargeAnalysis, Evidence, Dispute,
     Negotiation) sobre AgentCore Runtime, con Bedrock/Claude Sonnet 4.5 al lado
   - DynamoDB (cases, transactions, decisions), S3 (invoices, emails, evidence),
     EventBridge, CloudWatch
   - los dos mocks marcados claramente como "simulated external systems"
   - el punto de human-in-the-loop resaltado: es lo que nos diferencia, tiene que verse
   Usa la paleta de iconos oficial de AWS. Sin flechas cruzadas ni texto de 8pt.

2. Completa en el README raíz las secciones que dependen de infra: AWS Services Used (con
   para qué se usa cada uno, no solo la lista), Local Setup (el quick start real, probado
   desde cero), AWS Deployment, y Demo Credentials.

3. docs/demo-script.md: el guion minuto a minuto del video de 5 minutos, con qué comando
   correr en cada momento, qué se ve en pantalla y qué se dice. Incluye el punto exacto
   donde se muestra la decision card, que es el clímax de la demo.

4. docs/runbook.md: qué hacer si el demo falla en vivo. Orden de fallback: AWS real ->
   docker compose local -> video pregrabado.

5. Verificación final de higiene: `git grep -iE "AKIA|aws_secret|account_id\s*=\s*\"[0-9]"`
   sin resultados, y que .env no esté trackeado.

Criterio de aceptación: una persona ajena al equipo clona el repo, corre
`cp .env.example .env && make up && make seed` y ve el sistema funcionando sin preguntar
nada. Pídele a alguien del equipo que lo haga en una máquina limpia y pega el resultado.
```

---

## §10 — Prompt de auditoría (correr el 12 de septiembre)

```
Modo auditoría. No escribas features nuevas.

Revisa el repo completo contra los requisitos del hackathon y reporta hallazgos ordenados
por severidad, sin arreglar nada todavía:

Requisitos obligatorios del hackathon:
- ¿El agente está construido con Strands Agents SDK y se puede demostrar? (revisa agents/,
  aunque no sea tu carpeta: aquí solo auditas)
- ¿Repo público con README, diagrama de arquitectura y licencia MIT?
- ¿Está desplegado en Amazon Bedrock AgentCore, o está documentado el fallback?

Higiene:
- ¿Algún secreto, access key o account ID en el historial de git, no solo en HEAD?
  (git log -p | grep -iE "AKIA|aws_secret_access_key")
- ¿.env trackeado por accidente?
- ¿Alguna URL o credencial de demo que exponga algo que no debería ser público?
- ¿Recursos de AWS que cobren estando idle?
- ¿El README promete algo que el código no hace? Los jueces lo van a probar.

Reproducibilidad:
- Clona el repo en un directorio limpio y sigue el README al pie de la letra. Anota cada
  paso donde tuviste que adivinar algo. Cada uno de esos es un bug de documentación.

Entrega una tabla: severidad (bloqueante / alta / media / baja), hallazgo, archivo, arreglo
propuesto y a quién le toca. Sin arreglar nada.
```
