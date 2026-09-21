# HANDOFF — Proyecto Psycode: Resumen y Tareas Jira

> **Actualización de ejecución:** Martin autorizó generar las apps Django e implementar SCRUM-31. La base y autenticación están implementadas localmente; ver [docs/SCRUM-31.md](docs/SCRUM-31.md) y [README](README.md). Las notas de “fase actual SCRUM-30” siguientes describen el encargo original. No se modificaron estados en Jira; SCRUM-32 y posteriores siguen pendientes.

> **Para:** Modelo implementador (GPT Astra vía Codex)
> **De:** Martin Ferreira
> **Fecha:** 2026-09-12
> **Repo local:** `/Users/martin/Desktop/consultoria-bn/` — **nueva casa del proyecto**
> **Tablero Jira:** https://proyecto-team-psycode.atlassian.net/jira/software/projects/SCRUM/boards/1/backlog

---

## 0. ⚠️ ALCANCE — LEER PRIMERO

**Alcance único: las 11 tareas del tablero Jira (§2–§3). Nada más. Sin capas avanzadas y sin componentes pre-construidos: todo se construye desde cero.**

- Este proyecto **no** incluye pipeline de audio/transcripción, detección automática ni ningún módulo externo ya hecho (por ejemplo, notificadores preexistentes). **Si no está en Jira, no se construye.**
- **Fase actual: SCRUM-30** — definir nombres, patrones, arquitectura y contratos. **No se programa funcionalidad todavía.** SCRUM-31 y siguientes se harán **solo cuando Martin lo indique explícitamente**.

**Reglas explícitas de esta fase:**

1. SCRUM-30 fija los **nombres y patrones** para que el equipo trabaje **en paralelo sin dependencias**: el backend desarrolla según los patrones/arquitectura definidos; el frontend consume las APIs según los contratos (`API_CONTRACTS.md`).
2. **Buscar y proponer los mejores patrones de arquitectura y de capas** (presentación/API, aplicación/servicios, dominio, infraestructura; separación de responsabilidades), aplicados a Django.
3. **Stack por ahora: Python + Django.** Cualquier desviación se consulta primero.
4. **Documentación obligatoria en cada carpeta**: cuando se desarrolle código, cada carpeta debe incluir archivos Markdown (`.md`) explicando — para qué sirve esa carpeta, las rutas que habrá, métodos importantes, etc.

---

## 1. Contexto del proyecto

**Plataforma de gestión de alertas de riesgo** para una **clínica psicológica orientada a la prevención del suicidio** (Equipo Psycode, Chile).

El sistema gestiona las **alertas de riesgo** de las sesiones clínicas, de punta a punta:

| Función | Tareas |
|---|---|
| Autenticación y sesión de usuarios (SQLite) | SCRUM-31 · SCRUM-35 |
| Almacenamiento de alertas y evaluaciones (MongoDB) | SCRUM-32 |
| Consulta, filtros y detalle de alertas | SCRUM-33 · SCRUM-37 · SCRUM-39 |
| Registro de evaluaciones (Correcta / Falso positivo / Neutro) | SCRUM-34 · SCRUM-40 |
| Dashboard y estadísticas | SCRUM-36 |
| Notificaciones por Microsoft Teams (con contingencia por correo) | SCRUM-41 |

**Alerta = registro con:** identificador único, box, tipo de riesgo, nivel de severidad (semáforo), fecha/hora de detección, estado de evaluación, sesión asociada y trazabilidad.
**Evaluación de alerta:** `Correcta` | `Falso positivo` | `Neutro` (registrada por usuario, con fecha/hora).

### 1.1 Insumo clínico — Matriz de lenguaje de ideación suicida (Excel del cliente)

- Original: `docs/Matriz-lenguaje-ideacion-suicida.xlsx` · Transcripción: `docs/matriz-lenguaje-ideacion-suicida.md`.
- **Gradiente clínico** (fuente C-SSRS) que rige la severidad de las alertas:
  `0` sin ideación · `1` deseo pasivo de muerte · `2` ideación activa · `3` consideración de método · `4` intención · `5` plan · `6` conducta preparatoria · `7` conducta suicida.
- **Reglas de uso obligatorias**: una frase aislada no diagnostica; separar ideación / intención / plan / conducta; no registrar detalles operativos de métodos; no inventar frecuencias; validación clínica, cultural y externa antes de producción.
- Mapeo al semáforo operativo: ver **Anexo A** de `API_CONTRACTS.md`.

### 1.2 Punto de partida de esta carpeta

| Archivo | Qué es |
|---|---|
| `HANDOFF.md` | Este documento: alcance, reglas y las 11 tareas del Jira |
| `API_CONTRACTS.md` | Contratos de la API (alcance Jira): convenciones, auth, alertas, dashboard, notificaciones + Anexo A clínico |
| `docs/` | Insumos clínicos (Excel + transcripción + README) |

> Repositorio git inicializado y **sin commits todavía**.

---

## 2. Tablero Jira (11 tareas)

Todas en estado **"Por hacer"**. Prioridad `Highest` = núcleo del sistema; `Medium` = resto.

| ID | Título | Prioridad | Asignado | Área |
|---|---|---|---|---|
| SCRUM-30 | Definir patrón y contratos de las APIs del backend | 🔴 Highest | **Martin ferreira** | Backend |
| SCRUM-31 | Implementar autenticación y recuperación de contraseña con SQLite | 🔴 Highest | **Martin ferreira** | Backend |
| SCRUM-32 | Implementar persistencia de alertas en MongoDB | 🔴 Highest | Álvaro Farfán Reyes | Backend |
| SCRUM-33 | Implementar consulta de alertas y filtros | 🟡 Medium | Bernardo Arenas | Backend |
| SCRUM-34 | Implementar evaluación y actualización de alertas | 🟡 Medium | Alejandra Ulloa | Backend |
| SCRUM-35 | Implementar inicio de sesión, recuperación y manejo de sesión | 🟡 Medium | Bernardo Arenas | Frontend |
| SCRUM-36 | Implementar dashboard y estadísticas de alertas | 🟡 Medium | Sin asignar | Frontend |
| SCRUM-37 | Implementar historial y filtros de alertas en el frontend | 🟡 Medium | Danya Andrea Duran Fabres | Frontend |
| SCRUM-39 | Implementar detalle y evaluación de alertas en el frontend | 🟡 Medium | Danya Andrea Duran Fabres | Frontend |
| SCRUM-40 | Implementar registro de evaluaciones en el frontend | 🟡 Medium | Aarón Orellana | Frontend |
| SCRUM-41 | Implementar notificaciones mediante Microsoft Teams | 🟡 Medium | Sin asignar | Backend |

**Nota:** las tareas referencian requerimientos `RF-08…RF-19` de un documento de especificación del proyecto (externo a este repo).

> ⚠️ Este backlog es el **alcance completo del proyecto**. La única tarea en foco es SCRUM-30 (§0); las implementaciones (SCRUM-31+) empezarán cuando Martin lo indique.

---

## 3. Tareas en detalle (descripciones completas del Jira)


### 🎯 SCRUM-30 — Definir patrón y contratos de las APIs del backend — Highest — **Martin ferreira** — **EN FOCO (fase actual)**

Establecer el patrón de desarrollo que utilizará el backend para la creación y organización de sus APIs, definiendo la estructura de las rutas, métodos HTTP, formato de las solicitudes y respuestas, códigos de estado y manejo de errores. Esto permitirá que el frontend conozca cómo realizar las peticiones y qué respuesta esperar de cada ruta.

**Resultado esperado:**
- Definir el patrón de organización y nombramiento de las rutas del backend.
- Definir los métodos HTTP que utilizará cada tipo de operación.
- Establecer la estructura que tendrán las peticiones realizadas desde el frontend.
- Establecer la estructura y formato de las respuestas entregadas por el backend.
- Definir un ejemplo de ruta con su respectiva petición y respuesta esperada.
- Documentar los contratos de las rutas que serán utilizadas por el frontend.
- Establecer una estructura común que permita que las distintas funcionalidades del sistema mantengan el mismo formato de comunicación.
- Permitir que frontend y backend puedan desarrollar sus funcionalidades de forma independiente a partir de los contratos definidos.

**Estado:** SCRUM-30 documentada y lista para revisión del equipo (2026-09-12); no implica cierre en Jira ni implementación de funcionalidades. Arquitectura en [ARCHITECTURE.md](ARCHITECTURE.md), contratos consolidados en [API_CONTRACTS.md](API_CONTRACTS.md), estructura con README por carpeta en [backend/](backend/README.md) y criterios en [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md). SCRUM-31 y siguientes permanecen pendientes de activación explícita de Martin.

**Aclaración acordada con Martin en esta entrega:** conservar y completar rutas/campos del borrador; permitir librerías base Django REST Framework, Simple JWT y PyMongo. “Desde cero” aplica a la lógica y los componentes de negocio del proyecto, no a reimplementar autenticación criptográfica o controladores. No se modifica el backlog ni se cambia de stack.

---

### 🔴 SCRUM-31 — Implementar autenticación y recuperación de contraseña con SQLite — Highest — **Martin ferreira** — implementada localmente por autorización de Martin

Implementar el sistema de autenticación utilizando SQLite, incluyendo la validación de credenciales, gestión de sesión y recuperación de contraseña para los usuarios registrados. Además, crear un usuario de prueba que permita validar el funcionamiento del sistema durante el desarrollo.

**Resultado esperado:**
- Crear la estructura necesaria en SQLite para almacenar los usuarios.
- Implementar identificadores únicos para los usuarios.
- Almacenar el nombre de usuario y las credenciales de forma segura.
- Registrar el estado activo/inactivo de los usuarios.
- Crear un usuario de prueba con credenciales definidas para validar el funcionamiento de la autenticación.
- Validar las credenciales ingresadas contra SQLite.
- Rechazar credenciales incorrectas.
- Rechazar el acceso de usuarios inactivos o no registrados.
- Implementar el mecanismo de recuperación de contraseña.
- Validar que el usuario exista antes de iniciar la recuperación.
- Permitir establecer una nueva contraseña mediante el flujo de recuperación definido.
- Mantener la sesión del usuario autenticado.
- Restringir el acceso a las funcionalidades protegidas sin una sesión válida.
- Permitir cerrar sesión.
- Retornar respuestas apropiadas ante autenticación exitosa o fallida.
- Gestionar errores relacionados con la autenticación, recuperación de contraseña y sesión.
- Verificar el inicio y cierre de sesión utilizando el usuario de prueba.

*Requerimiento relacionado: RF-17.*

**Notas:** contratos de auth en `API_CONTRACTS.md` (§1). Implementación desde cero cuando Martin lo indique.

---

### 🔴 SCRUM-32 — Implementar persistencia de alertas en MongoDB — Highest — Álvaro Farfán Reyes

Implementar la conexión del backend con MongoDB y la estructura necesaria para almacenar la información generada por las alertas, sus evaluaciones y los datos necesarios para mantener su trazabilidad. Además, generar al menos cinco alertas de prueba que permitan validar el almacenamiento y las funcionalidades que utilizan estos datos.

**Resultado esperado:**
- Configurar la conexión del backend con MongoDB.
- Configurar las variables de entorno necesarias.
- Gestionar errores de conexión.
- Implementar la estructura o modelo de las alertas.
- Incorporar identificador único de la alerta.
- Incorporar box.
- Incorporar tipo de riesgo.
- Incorporar nivel de severidad.
- Incorporar fecha y hora de detección.
- Incorporar estado de evaluación.
- Incorporar la información necesaria para asociar la alerta con la sesión correspondiente.
- Incorporar la información necesaria para la trazabilidad.
- Permitir almacenar las evaluaciones asociadas a las alertas.
- Generar al menos 5 alertas de prueba en MongoDB.
- Utilizar datos variados en las alertas de prueba, considerando diferentes boxes, tipos de riesgo, niveles de severidad y estados de evaluación.
- Verificar que las alertas de prueba puedan ser almacenadas y posteriormente consultadas correctamente.
- Verificar el almacenamiento correcto de la información.
- No almacenar grabaciones completas de audio de las sesiones.

*Requerimientos relacionados: RF-11 y RF-18.*

**Notas:** campos de la alerta en `API_CONTRACTS.md` (§2). Esquema en `docs/MONGODB.md`. Persistencia local en [docs/SCRUM-32.md](docs/SCRUM-32.md): conexión PyMongo, repositorio y `seed_demo_alerts`. Las rutas HTTP de consulta/evaluación siguen pendientes.

---

### 🟡 SCRUM-33 — Implementar consulta de alertas y filtros — Medium — Bernardo Arenas

Implementar los servicios del backend necesarios para consultar las alertas almacenadas en MongoDB, obtener su detalle y aplicar los filtros disponibles en el historial.

**Resultado esperado:**
- Obtener el listado de alertas.
- Ordenar las alertas por fecha y hora.
- Filtrar por fecha.
- Filtrar por box.
- Filtrar por estado de evaluación.
- Permitir combinar filtros.
- Consultar una alerta específica mediante su identificador.
- Retornar la información necesaria para el historial.
- Retornar la información necesaria para el detalle de una alerta.
- Retornar el estado actual de evaluación.
- Manejar correctamente consultas sin resultados.
- Manejar alertas inexistentes.
- Manejar errores durante las consultas.

*Requerimientos relacionados: RF-15 y RF-16.*

---

### 🟡 SCRUM-34 — Implementar evaluación y actualización de alertas — Medium — Alejandra Ulloa

Implementar la funcionalidad del backend que permita registrar la evaluación de una alerta y actualizar su estado, manteniendo la información necesaria para la trazabilidad.

**Resultado esperado:**
- Asociar la evaluación con la alerta correspondiente.
- Permitir las evaluaciones:
  - Correcta.
  - Falso positivo.
  - Neutro.
- Validar que la evaluación seleccionada sea válida.
- Registrar el usuario que realizó la evaluación.
- Registrar la fecha y hora de la evaluación.
- Actualizar el estado de evaluación de la alerta.
- Registrar la información necesaria para la trazabilidad.
- Permitir consultar posteriormente la evaluación realizada.
- Manejar errores durante el registro o actualización.

*Requerimientos relacionados: RF-11, RF-16 y RF-18.*

**Notas:** contrato de evaluación en `API_CONTRACTS.md` (§2).

---

### 🟡 SCRUM-35 — Implementar inicio de sesión, recuperación y manejo de sesión — Medium — Bernardo Arenas

Desarrollar la interfaz de autenticación e integrarla con el backend, permitiendo al usuario iniciar sesión, recuperar su contraseña, gestionar su sesión y acceder de forma segura a las funcionalidades del sistema.

**Resultado esperado:**
- Incorporar campo de nombre de usuario o correo institucional.
- Incorporar campo de contraseña.
- Incorporar botón de inicio de sesión.
- Incorporar opción “¿Olvidaste tu contraseña?”.
- Implementar la interfaz correspondiente al flujo de recuperación de contraseña.
- Validar los campos antes de enviar las solicitudes.
- Mostrar mensajes ante credenciales incorrectas.
- Mostrar mensajes cuando el usuario no pueda iniciar el proceso de recuperación.
- Mostrar estado de carga durante las operaciones de autenticación y recuperación.
- Mostrar mensajes ante errores de conexión o del servidor.
- Mantener la sesión durante la navegación.
- Impedir el acceso a las funcionalidades protegidas cuando no exista una sesión válida.
- Permitir cerrar sesión.
- Redirigir al dashboard después de una autenticación exitosa.

*Requerimiento relacionado: RF-17.*

---

### 🟡 SCRUM-36 — Implementar dashboard y estadísticas de alertas — Medium — Sin asignar

Desarrollar el dashboard principal del sistema, permitiendo visualizar un resumen del estado de las alertas y acceder a la información estadística disponible.

**Resultado esperado:**
- Mostrar la cantidad de alertas del período correspondiente.
- Mostrar la cantidad de alertas pendientes.
- Mostrar la cantidad de alertas revisadas.
- Mostrar indicadores visuales diferenciados según el estado de las alertas.
- Permitir acceder al historial de alertas.
- Permitir acceder a las estadísticas.
- Mostrar las estadísticas de alertas por período.
- Permitir cambiar entre vista semanal y mensual.
- Mostrar la cantidad de alertas correspondiente al período seleccionado.
- Mostrar el registro histórico asociado al período.
- Permitir regresar al dashboard desde la vista estadística.
- Manejar correctamente la ausencia de información estadística.

---

### 🟡 SCRUM-37 — Implementar historial y filtros de alertas en el frontend — Medium — Danya Andrea Duran Fabres

Desarrollar la pantalla de historial de alertas, permitiendo visualizar, buscar y filtrar las alertas almacenadas y acceder a su detalle.

**Resultado esperado:**
- Mostrar el listado de alertas.
- Mostrar identificador de alerta.
- Mostrar box.
- Mostrar tipo de riesgo.
- Mostrar nivel de severidad mediante semáforo.
- Mostrar fecha.
- Mostrar hora.
- Mostrar estado de evaluación.
- Permitir seleccionar una alerta para revisar su detalle.
- Permitir buscar por identificador, box o tipo de riesgo.
- Incorporar filtro por fecha.
- Incorporar filtro por box.
- Incorporar filtro por estado.
- Permitir combinar filtros.
- Permitir limpiar los filtros.
- Actualizar el listado según los filtros aplicados.
- Mostrar un mensaje cuando no existan resultados.

---

### 🟡 SCRUM-39 — Implementar detalle y evaluación de alertas en el frontend — Medium — Danya Andrea Duran Fabres

Desarrollar el modal de detalle de alerta que se abre desde el historial, permitiendo visualizar la información de la alerta y registrar su evaluación.

**Resultado esperado:**
- Mostrar el identificador de la alerta.
- Mostrar box.
- Mostrar tipo de riesgo.
- Mostrar nivel de severidad.
- Mostrar fecha.
- Mostrar hora.
- Mostrar estado actual.
- Permitir cerrar el modal.
- Mostrar las opciones de evaluación:
  - Correcta.
  - Falso positivo.
  - Neutro.
- Validar la selección antes de guardar.
- Enviar la evaluación al backend.
- Mostrar estado de carga durante el registro.
- Mostrar confirmación cuando la evaluación se registre correctamente.
- Actualizar el estado de la alerta después de guardar.
- Mostrar mensajes ante errores.

*Requerimiento relacionado: RF-16.*

---

### 🟡 SCRUM-40 — Implementar registro de evaluaciones en el frontend — Medium — Aarón Orellana

Desarrollar la pantalla de registro de evaluaciones, permitiendo consultar las alertas que ya fueron evaluadas y visualizar el resultado de la evaluación realizada.

**Resultado esperado:**
- Mostrar el identificador de la alerta.
- Mostrar la evaluación seleccionada.
- Mostrar el resultado asociado a la revisión del sistema.
- Mostrar el estado de la alerta.
- Mostrar la fecha y hora de evaluación.
- Permitir acceder al detalle de una evaluación.
- Obtener la información desde el backend.
- Mostrar correctamente las evaluaciones realizadas.
- Manejar ausencia de resultados.
- Manejar errores de consulta.

*Requerimientos relacionados: RF-15, RF-16 y RF-18.*

---

### 🟡 SCRUM-41 — Implementar notificaciones mediante Microsoft Teams — Medium — Sin asignar

Implementar la integración del backend con Microsoft Teams para enviar notificaciones cuando el sistema genere una alerta de riesgo, incorporando la información definida para la notificación y considerando el manejo de errores, tiempos de espera y la contingencia mediante correo electrónico.

**Resultado esperado:**
- Configurar la integración del backend con Microsoft Teams.
- Configurar las variables de entorno necesarias para la conexión.
- Implementar el mecanismo para enviar una notificación cuando se genere una alerta de riesgo.
- Incluir en la notificación:
  - Box donde se detectó la alerta.
  - Tipo de riesgo detectado.
  - Nivel de urgencia mediante semáforo.
  - Fecha y hora de detección.
- Mantener una estructura común para las notificaciones enviadas.
- No incluir datos personales directos del paciente en la notificación.
- Gestionar errores de comunicación con Microsoft Teams.
- Definir y gestionar un tiempo máximo de espera para la respuesta de la API.
- Registrar los errores y fallos de envío en el sistema de auditoría.
- Implementar el mecanismo de contingencia para enviar la notificación mediante correo electrónico cuando Teams no se encuentre disponible.
- Registrar cuando se utilice la notificación mediante correo como alternativa.
- Verificar el envío de notificaciones mediante datos de prueba.
- Verificar el funcionamiento de la contingencia ante una falla de Teams.

*Requerimientos relacionados: RF-08, RF-11, RF-13 y RF-19.*

**Notas:** contrato interno de la notificación en `API_CONTRACTS.md` (§4).


---

## 4. Reglas del proyecto y próximos pasos

### 4.1 Reglas explícitas (aplican a todo el desarrollo)

1. **Mejores patrones de arquitectura y de capas, etcétera.** El diseño por capas (presentación/API, aplicación/servicios, dominio, infraestructura) queda definido y documentado antes de programar — es la base para que las tareas de cada equipo no dependan entre sí.
2. **Por el momento, todo se realiza en Python y en Django.** Cualquier desviación se consulta antes de avanzar.
3. **Documentación en cada carpeta**: desde que se empiece a desarrollar código, cada carpeta debe contener archivos `.md` explicando — para qué sirve esa carpeta, las rutas que habrá, métodos importantes, etc.

### 4.2 Orden de implementación (futuro — solo cuando Martin lo indique)

1. **SCRUM-30** — actual (definiciones: nombres, patrones, arquitectura, contratos).
2. **SCRUM-31** — autenticación y recuperación de contraseña (SQLite).
3. **SCRUM-32** — persistencia de alertas (MongoDB).
4. **SCRUM-33 → SCRUM-34** — consulta/filtros y evaluación (backend).
5. **SCRUM-41** — notificaciones por Microsoft Teams.
6. **Frontend: SCRUM-35 → 36/37 → 39/40** — pantallas (el stack frontend se definirá al activar esas tareas).

> ⛔ Mientras SCRUM-30 no esté consolidada: **no se escribe código de funcionalidades.**

---

## 5. Restricciones importantes

- 🚫 **Solo alcance Jira** — sin capas avanzadas ni componentes pre-construidos; construcción desde cero.
- 🚫 **No programar funcionalidad aún** — la fase actual es SCRUM-30: patrones, arquitectura, nombres y contratos.
- 🔒 **Privacidad**: no se almacenan grabaciones de audio de las sesiones; las notificaciones no llevan datos personales del paciente (solo box, tipo de riesgo, semáforo, fecha/hora).
- 📄 Los `RF-xx` citados vienen del documento de especificación del proyecto (externo a este repo).
- 🐍 Python 3.10+; entornos con PEP 668 — usar venv (`python -m venv .venv` o `uv venv`).
- 📐 Respetar los contratos de `API_CONTRACTS.md`: el frontend se desarrolla en paralelo contra ellos.

---

*Documento generado a partir del tablero Jira (11 tareas) y los insumos del cliente. Fase actual: SCRUM-30.*
